"""kb-API gateway entry point.

Единая точка входа FastAPI-приложения. Все routers подключаются через
include_router. См. ADR-0005 для обоснования выбора FastAPI.

Lifespan управляет webhook delivery worker'ом (E5.2 #89): запускается
при app startup если `Settings.webhook_worker_enabled=True`, gracefully
stops at shutdown.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.api.admin.pd_overdue_worker import PdOverdueWorker
from src.api.admin.task_reaper import reap_stale_tasks
from src.api.admin.task_runner import init_runner
from src.api.chat.cleanup_worker import ChatCleanupWorker
from src.api.chat.llm.factory import close_llm_provider, init_llm_provider
from src.api.config import get_settings
from src.api.db import get_engine
from src.api.observability import (
    MetricsMiddleware,
    RequestIdMiddleware,
    install_json_log_formatter,
    install_request_id_filter,
    render_metrics,
)
from src.api.outbox.cleanup_worker import OutboxCleanupWorker
from src.api.outbox.drainer import close_drainer, init_drainer
from src.api.v1.router import router as v1_router
from src.api.webhooks.cleanup_worker import WebhookCleanupWorker
from src.api.webhooks.worker import WebhookDeliveryWorker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """FastAPI lifespan:
    - start/stop webhook delivery worker.
    - init AdminTaskRunner singleton.
    - init LLMProvider singleton (#350 — connection pool reuse).
    - reap stale admin_tasks on startup (ADR-0020 §«Crash recovery»).
    """
    settings = get_settings()
    engine = get_engine()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # ADR-0020 B: initialize singleton task runner.
    init_runner(session_factory, settings)
    logger.info("admin_task_runner.initialized")

    # #350: initialize LLMProvider singleton — connection pool reuse.
    # Failures (missing creds для gigachat/yandex_gpt) логируем но не
    # блокируем startup: lazy init попробует ещё раз на первом chat
    # request'е, и если провалится — chat вернёт 5xx с понятной ошибкой
    # (admin может переключиться на mock через PATCH /admin/system-config).
    try:
        init_llm_provider(settings)
        logger.info("llm_provider.initialized", extra={"provider": settings.llm_provider})
    except Exception:
        logger.exception("llm_provider.init_failed", extra={"provider": settings.llm_provider})

    # #356 / ADR-0026: initialize OutboxDrainer singleton (env-gated).
    # При `OUTBOX_DRAINER_ENABLED=False` — no-op; webhook dispatcher
    # использует legacy direct path. Failures логируются но не блокируют
    # startup (acceptable degradation: outbox rows накопятся и flush'нутся
    # при следующем successful start'е).
    try:
        init_drainer(session_factory, settings)
        if settings.outbox_drainer_enabled:
            logger.info("outbox.drainer.initialized")
    except Exception:
        logger.exception("outbox.drainer.init_failed")

    # ADR-0020 §Crash recovery: scan orphaned tasks (>15min stale).
    try:
        await reap_stale_tasks(session_factory)
    except Exception:
        logger.exception("admin_task_reaper.failed_on_startup")

    worker: WebhookDeliveryWorker | None = None
    if settings.webhook_worker_enabled:
        worker = WebhookDeliveryWorker(
            session_factory=session_factory,
            settings=settings,
        )
        worker.start()
        logger.info("webhook.worker.started")

    # #340: PD requests OVERDUE auto-transition (ФЗ-152 §15 SLA).
    pd_worker: PdOverdueWorker | None = None
    if settings.pd_overdue_worker_enabled:
        pd_worker = PdOverdueWorker(
            session_factory=session_factory,
            settings=settings,
        )
        pd_worker.start()
        logger.info("pd_overdue.worker.started")

    # #341: Chat session cleanup (ФЗ-152 §21 right-to-forget).
    chat_worker: ChatCleanupWorker | None = None
    if settings.chat_cleanup_worker_enabled:
        chat_worker = ChatCleanupWorker(
            session_factory=session_factory,
            settings=settings,
        )
        chat_worker.start()
        logger.info("chat_cleanup.worker.started")

    # #342: Webhook config cleanup (ФЗ-152 §21, soft-deleted past retention).
    webhook_cleanup: WebhookCleanupWorker | None = None
    if settings.webhook_cleanup_worker_enabled:
        webhook_cleanup = WebhookCleanupWorker(
            session_factory=session_factory,
            settings=settings,
        )
        webhook_cleanup.start()
        logger.info("webhook_cleanup.worker.started")

    # ADR-0026 Slice 4: physical-delete flushed outbox rows past retention.
    outbox_cleanup: OutboxCleanupWorker | None = None
    if settings.outbox_cleanup_worker_enabled:
        outbox_cleanup = OutboxCleanupWorker(
            session_factory=session_factory,
            settings=settings,
        )
        outbox_cleanup.start()
        logger.info("outbox_cleanup.worker.started")
    try:
        yield
    finally:
        if worker is not None:
            await worker.stop()
            logger.info("webhook.worker.stopped")
        if pd_worker is not None:
            await pd_worker.stop()
            logger.info("pd_overdue.worker.stopped")
        if chat_worker is not None:
            await chat_worker.stop()
            logger.info("chat_cleanup.worker.stopped")
        if webhook_cleanup is not None:
            await webhook_cleanup.stop()
            logger.info("webhook_cleanup.worker.stopped")
        if outbox_cleanup is not None:
            await outbox_cleanup.stop()
            logger.info("outbox_cleanup.worker.stopped")
        # #350: close LLMProvider httpx client pool. Idempotent —
        # no-op если init не успел отработать.
        try:
            await close_llm_provider()
            logger.info("llm_provider.closed")
        except Exception:
            logger.exception("llm_provider.close_failed")
        # #356 / ADR-0026: graceful drainer shutdown.
        try:
            await close_drainer()
            logger.info("outbox.drainer.closed")
        except Exception:
            logger.exception("outbox.drainer.close_failed")


app = FastAPI(
    title="reHome Knowledge Base API",
    description=(
        "Gateway модуля базы знаний reHome. "
        "Полный контракт — в docs/handoff/01_postanovka/04_openapi.yaml."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# #106: X-Request-Id propagation + structured logging context.
# `app.add_middleware` LIFO: последний add'ed middleware — outermost.
# Порядок (внутрь → наружу): MetricsMiddleware (#108) → RequestIdMiddleware (#106).
# RequestId должен оставаться OUTERMOST — все логи (incl. metrics middleware'а)
# наследуют request_id.
install_request_id_filter()
# #110: JSON log formatter — install'им если `LOG_FORMAT=json` (prod
# log aggregators ожидают structured output). Default `text` для dev.
if get_settings().log_format == "json":
    install_json_log_formatter()
app.add_middleware(MetricsMiddleware)
app.add_middleware(RequestIdMiddleware)


# #108: Prometheus pull endpoint. Намеренно НЕ под /api/v1 (infra, не
# публичный API) и БЕЗ auth. Gate'им через `METRICS_ENABLED` env-flag —
# safe-by-default (404 если не выставлен, чтобы scrape policy на
# reverse-proxy не была единственной защитой).
@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint() -> Response:
    if not get_settings().metrics_enabled:
        return Response(status_code=404)
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


app.include_router(v1_router)
