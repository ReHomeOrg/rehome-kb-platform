"""PopularQueryWorker (#220, ТЗ §5.1).

Daily scan `search_query_log`:
  1. `find_popular_unanswered(window_hours, min_count)` → list[query,count].
  2. Если непусто — `dispatcher.dispatch("search.popular_query", payload)`.
  3. Payload shape: `{"queries": [{"query": str, "count": int}, ...],
     "window_hours": int, "min_count": int}` — frozen контракт для
     subscriber'ов.

**Cadence** — default 24h (raз в сутки, как требует ТЗ).

**Idempotency** — НЕ tracked: один scan tick = один dispatch. Re-emit
acceptable (subscriber'ы dedup'ят через event_id если нужно). Это same
trade-off как у `vault_reminders`.

**Empty result** — НЕ dispatch'им. `queries=[]` payload — шум для
subscriber'ов; пусть webhook молчит когда нет hot queries.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.config import get_settings
from src.api.outbox.repository import OutboxRepository
from src.api.search.query_log import SearchQueryLogRepository
from src.api.webhooks.delivery_repository import WebhookDeliveryRepository
from src.api.webhooks.dispatcher import WebhookEventDispatcher
from src.api.webhooks.events import WebhookEvent
from src.api.webhooks.repository import WebhookRepository
from src.workers.popular_query.metrics import (
    DISPATCH_TOTAL,
    QUERIES_EMITTED,
    SCAN_DURATION_SECONDS,
    SCAN_ERRORS_TOTAL,
    SCAN_TOTAL,
)

logger = logging.getLogger(__name__)

SessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class PopularQueryWorker:
    """Daily popular-unanswered scanner + webhook emitter."""

    def __init__(
        self,
        *,
        session_factory: SessionContextFactory,
        window_hours: int = 24,
        min_count: int = 3,
        max_queries: int = 50,
        scan_interval_seconds: float = 86400.0,
    ) -> None:
        self._session_factory = session_factory
        self._window_hours = window_hours
        self._min_count = min_count
        self._max_queries = max_queries
        self._interval = scan_interval_seconds
        self._stop_event = asyncio.Event()

    def request_stop(self) -> None:
        logger.info("popular_query.stop_requested")
        self._stop_event.set()

    async def run_forever(self) -> None:
        logger.info(
            "popular_query.start",
            extra={
                "window_hours": self._window_hours,
                "min_count": self._min_count,
                "scan_interval_seconds": self._interval,
            },
        )
        while not self._stop_event.is_set():
            try:
                emitted = await self.run_once()
            except Exception:
                logger.exception("popular_query.scan_failed")
                SCAN_ERRORS_TOTAL.inc()
                emitted = 0
            logger.info("popular_query.scan_done", extra={"emitted_queries": emitted})
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
        logger.info("popular_query.stopped")

    async def run_once(self) -> int:
        """One scan tick. Returns count of queries в emitted payload
        (0 если ничего не dispatch'илось)."""
        SCAN_TOTAL.inc()
        started = time.perf_counter()
        try:
            async with self._session_factory() as session:
                query_log = SearchQueryLogRepository(session)
                popular = await query_log.find_popular_unanswered(
                    window_hours=self._window_hours,
                    min_count=self._min_count,
                    limit=self._max_queries,
                )
                if not popular:
                    return 0

                # ADR-0026 Slice 0: dispatcher теперь signature имеет
                # outbox_repo + outbox_enabled. Worker reads env-flag —
                # дефолт False (legacy direct path), True → outbox routing.
                settings = get_settings()
                dispatcher = WebhookEventDispatcher(
                    webhook_repo=WebhookRepository(session),
                    delivery_repo=WebhookDeliveryRepository(session),
                    outbox_repo=OutboxRepository(session),
                    outbox_enabled=settings.outbox_drainer_enabled,
                )
                payload = {
                    "queries": [{"query": p.query, "count": p.count} for p in popular],
                    "window_hours": self._window_hours,
                    "min_count": self._min_count,
                }
                enqueued = await dispatcher.dispatch(
                    event_type=WebhookEvent.SEARCH_POPULAR_QUERY.value,
                    payload=payload,
                )
                # Webhook repo / dispatcher не commit'ит сам — нам нужно
                # явно commit'нуть, т.к. в worker context нет
                # request-lifecycle dependency injection.
                await session.commit()
                DISPATCH_TOTAL.inc()
                QUERIES_EMITTED.observe(len(popular))
                logger.info(
                    "popular_query.dispatched",
                    extra={
                        "queries_count": len(popular),
                        "subscribers": enqueued,
                    },
                )
                return len(popular)
        finally:
            SCAN_DURATION_SECONDS.observe(time.perf_counter() - started)


def install_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    worker: PopularQueryWorker,
) -> None:
    """SIGTERM/SIGINT → graceful stop (matches indexer / vault_reminders)."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, worker.request_stop)


__all__ = [
    "PopularQueryWorker",
    "SessionContextFactory",
    "install_signal_handlers",
]
