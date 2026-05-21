"""PD requests OVERDUE auto-transition worker (ФЗ-152 §15, #340).

Periodic background coroutine, lifecycle-managed через FastAPI lifespan.
Pattern mirrors `webhooks/worker.py::WebhookDeliveryWorker`.

ФЗ-152 §15: SAR (субъектный запрос) processing SLA = 30 days. После
истечения due_at заявка должна автоматически перейти в OVERDUE статус
для admin alerting + compliance reporting. Manual periodic admin
intervention — не масштабируется; этот worker делает auto-transition.

Не emit'ит security_incident (это organizational event, не breach).
Audit row тоже не пишет (admin запросы видны через regular admin/
personal-data/requests endpoint с status=OVERDUE filter).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from src.api.admin.pd_requests_repository import PersonalDataRequestRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.api.config import Settings

logger = logging.getLogger(__name__)


class PdOverdueWorker:
    """Asyncio worker для PD requests OVERDUE auto-transition.

    Lifecycle: caller calls `start()` (создаёт background task), позже
    `stop()` (signal shutdown + cancel + await graceful exit).
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
        self._task = asyncio.create_task(self._loop(), name="pd-overdue-worker")

    async def stop(self) -> None:
        """Graceful shutdown: signal + cancel + await."""
        self._shutdown.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        """Main poll loop. Catches exceptions per-iteration чтобы не упасть."""
        interval = self._settings.pd_overdue_worker_poll_interval_seconds
        while not self._shutdown.is_set():
            try:
                await self._run_once()
            except Exception:
                logger.exception("pd_overdue.worker.loop_error")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval)

    async def _run_once(self) -> int:
        """Single poll iteration. Returns count rows transitioned to OVERDUE."""
        async with self._session_factory() as session:
            repo = PersonalDataRequestRepository(session)
            count = await repo.mark_overdue()
            if count > 0:
                await session.commit()
                logger.info("pd_overdue.transitioned", extra={"count": count})
            return count


__all__ = ["PdOverdueWorker"]
