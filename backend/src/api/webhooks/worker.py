"""Background webhook delivery worker (E5.2 #89).

Asyncio task: запускается в FastAPI lifespan если
`Settings.webhook_worker_enabled=True`. Poll'ит outbox каждые
`webhook_worker_poll_interval_seconds`.

Pipeline:
1. claim_pending(batch=10) — claim due deliveries.
2. Для каждого: load webhook (для url + secret) → HMAC sign body →
   httpx POST.
3. 2xx → mark_delivered. Иначе → mark_failed (с exponential backoff
   или dead_letter после max_attempts).

Тестирование: worker НЕ автостартует в unit tests (env-flag default
False). Methods _deliver_one + _run_once тестируются напрямую.
"""

import asyncio
import contextlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.api.webhooks.delivery_repository import WebhookDeliveryRepository
from src.api.webhooks.metrics import (
    DELIVERIES_TOTAL,
    DELIVERY_DURATION_SECONDS,
    RETRIES_TOTAL,
    classify_status,
)
from src.api.webhooks.models import Webhook
from src.api.webhooks.signing import SIGNATURE_HEADER, compute_signature

if TYPE_CHECKING:
    from src.api.config import Settings

logger = logging.getLogger(__name__)


class WebhookDeliveryWorker:
    """Asyncio-based webhook delivery worker.

    Lifecycle: caller вызывает `start()` (создаёт background task),
    позже `stop()` (cancel + await graceful shutdown).
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[Any],
        settings: "Settings",
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        self._shutdown = asyncio.Event()
        self._http_client = httpx.AsyncClient(
            timeout=settings.webhook_delivery_timeout_seconds,
        )

    def start(self) -> None:
        """Создаёт background task. Idempotent."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="webhook-delivery-worker")

    async def stop(self) -> None:
        """Graceful shutdown: signal + cancel + await."""
        self._shutdown.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._http_client.aclose()

    async def _loop(self) -> None:
        """Main poll loop. Сам ловит exceptions, чтобы не упасть навсегда."""
        interval = self._settings.webhook_worker_poll_interval_seconds
        while not self._shutdown.is_set():
            try:
                await self._run_once()
            except Exception:
                # Defensive: НЕ падаем worker на одиночной ошибке.
                # Конкретные delivery errors уже обработаны в _deliver_one.
                logger.exception("webhook.worker.loop_error")
            # `asyncio.wait_for` rises TimeoutError если interval прошёл
            # без shutdown signal — это normal flow (продолжаем poll'ить).
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)

    async def _run_once(self) -> int:
        """Single poll iteration. Returns count delivered/failed."""
        async with self._session_factory() as session:
            repo = WebhookDeliveryRepository(session)
            deliveries = await repo.claim_pending(limit=10)
            if not deliveries:
                return 0

            # Load webhooks (нужны url + secret).
            webhook_ids: set[UUID] = {d.webhook_id for d in deliveries}
            webhooks: dict[UUID, Webhook] = {}
            for wid in webhook_ids:
                wh = await session.get(Webhook, wid)
                if wh is not None:
                    webhooks[wh.id] = wh

        # Process deliveries вне DB-сессии (HTTP может занять время).
        processed = 0
        for delivery in deliveries:
            webhook = webhooks.get(delivery.webhook_id)
            if webhook is None:
                # Webhook удалён (CASCADE сработал между claim и process'ом).
                # Игнорируем — delivery станет orphan'ом, cleanup задача backlog.
                continue
            await self._deliver_one(
                delivery_id=delivery.id,
                webhook=webhook,
                payload=delivery.payload,
                event_type=delivery.event_type,
                attempt_count=delivery.attempt_count,
            )
            processed += 1
        return processed

    async def _deliver_one(
        self,
        *,
        delivery_id: UUID,
        webhook: Webhook,
        payload: dict[str, Any],
        event_type: str,
        attempt_count: int = 0,
    ) -> None:
        """Sign + POST + mark_delivered/failed.

        `attempt_count` — текущее значение counter'а в БД (0 на первой
        попытке, >=1 после fail'ов). Используется для retry metric'и.
        """
        body_bytes = json.dumps(
            {"event": event_type, "data": payload},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = compute_signature(webhook.secret, body_bytes)

        if attempt_count >= 1:
            # Это retry — incrementим счётчик до посылки.
            RETRIES_TOTAL.labels(event_type=event_type).inc()

        async with self._session_factory() as session:
            repo = WebhookDeliveryRepository(session)
            started_at = time.perf_counter()
            status_code: int | None = None
            try:
                response = await self._http_client.post(
                    webhook.url,
                    content=body_bytes,
                    headers={
                        "Content-Type": "application/json",
                        SIGNATURE_HEADER: signature,
                        "X-Rehome-Event": event_type,
                    },
                )
                status_code = response.status_code
            except httpx.HTTPError as exc:
                duration = time.perf_counter() - started_at
                DELIVERY_DURATION_SECONDS.labels(event_type=event_type).observe(duration)
                DELIVERIES_TOTAL.labels(
                    event_type=event_type,
                    status=classify_status(None),
                ).inc()
                logger.warning(
                    "webhook.delivery.network_error",
                    extra={"delivery_id": str(delivery_id), "error": str(exc)},
                )
                await repo.mark_failed(
                    delivery_id,
                    status_code=None,
                    error=f"network: {exc!s}",
                    max_attempts=self._settings.webhook_max_attempts,
                    backoff_base_seconds=self._settings.webhook_backoff_base_seconds,
                )
                return

            duration = time.perf_counter() - started_at
            DELIVERY_DURATION_SECONDS.labels(event_type=event_type).observe(duration)
            DELIVERIES_TOTAL.labels(
                event_type=event_type,
                status=classify_status(status_code),
            ).inc()

            if 200 <= status_code < 300:
                await repo.mark_delivered(delivery_id, status_code=status_code)
            else:
                response_snippet = response.text[:200]
                logger.info(
                    "webhook.delivery.non_2xx",
                    extra={
                        "delivery_id": str(delivery_id),
                        "status_code": status_code,
                    },
                )
                await repo.mark_failed(
                    delivery_id,
                    status_code=status_code,
                    error=f"http {status_code}: {response_snippet}",
                    max_attempts=self._settings.webhook_max_attempts,
                    backoff_base_seconds=self._settings.webhook_backoff_base_seconds,
                )
