"""OutboxCleanupWorker — physical-delete flushed outbox rows past retention
(ADR-0026 Slice 4).

Mirrors `webhooks/cleanup_worker.py::WebhookCleanupWorker`. Only flushed
rows (`flushed_at IS NOT NULL`) удаляются — unflushed остаются для
drainer retry'ев. Retention default 30 days per ADR-0026 open-question 4.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.api.outbox.repository import OutboxRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.api.config import Settings

logger = logging.getLogger(__name__)


class OutboxCleanupWorker:
    """Asyncio worker для physical outbox-row cleanup."""

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
        self._task = asyncio.create_task(self._loop(), name="outbox-cleanup-worker")

    async def stop(self) -> None:
        self._shutdown.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        interval = self._settings.outbox_cleanup_poll_interval_seconds
        while not self._shutdown.is_set():
            try:
                await self._run_once()
            except Exception:
                logger.exception("outbox_cleanup.worker.loop_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)

    async def _run_once(self) -> int:
        retention = timedelta(days=self._settings.outbox_cleanup_retention_days)
        async with self._session_factory() as session:
            repo = OutboxRepository(session)
            count = await repo.hard_delete_flushed(retention=retention)
            if count > 0:
                await session.commit()
                logger.info(
                    "outbox_cleanup.deleted",
                    extra={"count": count, "retention_days": retention.days},
                )
            return count


__all__ = ["OutboxCleanupWorker"]
