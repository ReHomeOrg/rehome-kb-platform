"""OutboxDrainer background worker (#356, ADR-0026).

Periodic poll: fetch unflushed outbox rows → fan-out через
WebhookDeliveryRepository.enqueue per subscriber → mark_flushed.

Lifecycle mirrors `WebhookDeliveryWorker` / `PdOverdueWorker` / `LLMProvider`
singleton pattern (per ADR-0020 / #350):
- `init_drainer(session_factory, settings)` в FastAPI lifespan startup.
- `close_drainer()` в shutdown — signal + cancel + await graceful exit.

При `outbox_drainer_enabled=False` drainer не start'ится — outbox rows
накапливаются в таблице, но никто их не flush'ит (split-pod deploy, где
drainer запускается отдельным процессом). Default `True` — single-process
deployment получает webhook delivery «из коробки».
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from src.api.outbox.repository import OutboxRepository
from src.api.webhooks.delivery_repository import WebhookDeliveryRepository
from src.api.webhooks.repository import WebhookRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.api.config import Settings

logger = logging.getLogger(__name__)


class OutboxDrainer:
    """Background poll loop: drains outbox rows → webhook_deliveries queue.

    Per-iteration exception handling: failures bump retries counter on
    row, drainer continues. Row остаётся unflushed → retry на next
    iteration.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[Any],
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        self._shutdown = asyncio.Event()

    def start(self) -> None:
        """Создаёт background asyncio task. Idempotent."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="outbox-drainer")

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._shutdown.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        """Poll loop. Per-iteration `except Exception` чтобы drainer
        survived random DB hiccups."""
        interval = self._settings.outbox_drainer_poll_interval_seconds
        while not self._shutdown.is_set():
            try:
                await self._drain_once()
            except Exception:
                logger.exception("outbox.drainer.loop_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)

    async def _drain_once(self) -> int:
        """Single iteration: fetch batch, fan-out, mark_flushed.

        Returns count drained (для tests + observability).
        """
        batch_size = self._settings.outbox_drainer_batch_size
        async with self._session_factory() as session:
            outbox_repo = OutboxRepository(session)
            webhook_repo = WebhookRepository(session)
            delivery_repo = WebhookDeliveryRepository(session)
            rows = await outbox_repo.fetch_unflushed(limit=batch_size)
            if not rows:
                return 0

            drained = 0
            for row in rows:
                try:
                    subscribers = await webhook_repo.list_subscribers(row.event_type)
                    for webhook in subscribers:
                        await delivery_repo.enqueue(
                            webhook_id=webhook.id,
                            event_type=row.event_type,
                            payload=row.payload,
                        )
                    await outbox_repo.mark_flushed(row.id)
                    drained += 1
                except Exception as exc:
                    logger.exception(
                        "outbox.drainer.row_failed",
                        extra={
                            "outbox_id": str(row.id),
                            "event_type": row.event_type,
                        },
                    )
                    await outbox_repo.record_failure(row.id, error=str(exc))
            await session.commit()
            if drained > 0:
                logger.info("outbox.drainer.flushed", extra={"count": drained})
            return drained


# ---------------------------------------------------------------------------
# Singleton lifecycle (per ADR-0026 + #350 LLMProvider precedent)


_drainer_instance: OutboxDrainer | None = None


def init_drainer(
    session_factory: async_sessionmaker[Any],
    settings: Settings,
) -> OutboxDrainer | None:
    """Initialize drainer singleton + start background task.

    No-op (returns None) если `outbox_drainer_enabled=False` — outbox rows
    накапливаются, но не flush'атся (используется когда drainer работает
    в отдельном pod'е). Idempotent при repeat call.
    """
    global _drainer_instance
    if not settings.outbox_drainer_enabled:
        return None
    if _drainer_instance is None:
        _drainer_instance = OutboxDrainer(
            session_factory=session_factory,
            settings=settings,
        )
        _drainer_instance.start()
    return _drainer_instance


async def close_drainer() -> None:
    """Lifespan shutdown — graceful stop. Idempotent (no-op if not init'd)."""
    global _drainer_instance
    if _drainer_instance is None:
        return
    await _drainer_instance.stop()
    _drainer_instance = None


__all__ = ["OutboxDrainer", "close_drainer", "init_drainer"]
