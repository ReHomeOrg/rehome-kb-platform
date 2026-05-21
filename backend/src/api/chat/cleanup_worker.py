"""Chat cleanup worker — physical delete soft-deleted + expired sessions
(ФЗ-152 §21 right-to-forget, #341).

Periodic background coroutine, lifecycle-managed через FastAPI lifespan.
Pattern mirrors `admin/pd_overdue_worker.py::PdOverdueWorker`.

ФЗ-152 §21: soft-deleted records (user requested right-to-forget) должны
быть physically removed после reasonable retention window. Worker:
- physical-DELETE chat_sessions с deleted_at < (now - retention_days).
- physical-DELETE expired sessions (expires_at < now AND deleted_at IS NULL)
  — garbage cleanup, never-read-after-expiry.
- CASCADE на chat_messages через FK ondelete=CASCADE (см. chat/models.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.api.chat.repository import ChatRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.api.config import Settings

logger = logging.getLogger(__name__)


class ChatCleanupWorker:
    """Asyncio worker для physical chat-session cleanup.

    Lifecycle: `start()` → background task; `stop()` → graceful shutdown.
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
        """Создаёт background task. Idempotent."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="chat-cleanup-worker")

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._shutdown.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        """Main poll loop. Per-iteration exception caught (loop survives)."""
        interval = self._settings.chat_cleanup_poll_interval_seconds
        while not self._shutdown.is_set():
            try:
                await self._run_once()
            except Exception:
                logger.exception("chat_cleanup.worker.loop_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)

    async def _run_once(self) -> int:
        """Single poll iteration. Returns count deleted."""
        retention = timedelta(days=self._settings.chat_cleanup_retention_days)
        async with self._session_factory() as session:
            repo = ChatRepository(session)
            count = await repo.hard_delete_stale_sessions(
                soft_delete_retention=retention,
            )
            if count > 0:
                await session.commit()
                logger.info(
                    "chat_cleanup.deleted",
                    extra={"count": count, "retention_days": retention.days},
                )
            return count


__all__ = ["ChatCleanupWorker"]
