"""Webhook cleanup worker — physical delete soft-deleted configs
(ФЗ-152 §21, #342).

Mirrors `chat/cleanup_worker.py::ChatCleanupWorker`. Difference: no
`expires_at` semantics — webhook configs только soft-deleted через
owner unsubscribe, не auto-expire. Deliveries CASCADE через
ForeignKey ondelete=CASCADE (см. webhooks/models.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.api.webhooks.repository import WebhookRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.api.config import Settings

logger = logging.getLogger(__name__)


class WebhookCleanupWorker:
    """Asyncio worker для physical webhook-config cleanup."""

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
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="webhook-cleanup-worker")

    async def stop(self) -> None:
        self._shutdown.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        interval = self._settings.webhook_cleanup_poll_interval_seconds
        while not self._shutdown.is_set():
            try:
                await self._run_once()
            except Exception:
                logger.exception("webhook_cleanup.worker.loop_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)

    async def _run_once(self) -> int:
        retention = timedelta(days=self._settings.webhook_cleanup_retention_days)
        async with self._session_factory() as session:
            repo = WebhookRepository(session)
            count = await repo.hard_delete_soft_deleted(retention=retention)
            if count > 0:
                await session.commit()
                logger.info(
                    "webhook_cleanup.deleted",
                    extra={"count": count, "retention_days": retention.days},
                )
            return count


__all__ = ["WebhookCleanupWorker"]
