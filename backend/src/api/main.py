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

from src.api.config import get_settings
from src.api.db import get_engine
from src.api.observability import (
    MetricsMiddleware,
    RequestIdMiddleware,
    install_request_id_filter,
    render_metrics,
)
from src.api.v1.router import router as v1_router
from src.api.webhooks.worker import WebhookDeliveryWorker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """FastAPI lifespan: start/stop webhook delivery worker.

    `app` parameter required by FastAPI contract — unused в нашем case'е
    (worker конфигурируется через global settings, не через app state).
    """
    settings = get_settings()
    worker: WebhookDeliveryWorker | None = None
    if settings.webhook_worker_enabled:
        engine = get_engine()
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        worker = WebhookDeliveryWorker(
            session_factory=session_factory,
            settings=settings,
        )
        worker.start()
        logger.info("webhook.worker.started")
    try:
        yield
    finally:
        if worker is not None:
            await worker.stop()
            logger.info("webhook.worker.stopped")


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
