"""VaultReminderWorker (#167).

Scans `vault_secrets.expires_at` для secrets expiring soon (default 7 days
ahead) и emit'ит structured log notification per (secret_id, owner_id).

**Zero-knowledge invariant** (ADR-0011): worker НЕ recipient'ит plaintext
secret. Logs только: secret_id, owner_id, days_until_expiry, category.
Никакого title decryption / payload access.

**Notification channel** — structured JSON log (event=`vault.reminder`).
Real email/Telegram delivery — отдельный follow-up cube (требует SMTP /
bot config). Logging — sufficient для Loki/ELK alerting.

**Idempotency** — каждый scan повторно emit'ит для одного и того же
secret (downstream sink dedup'ит). Альтернатива (мутировать row с
`last_reminded_at`) — требует write transaction; punt'им до landing
follow-up'а с email.

**Cadence** — default 1 раз в сутки (`SCAN_INTERVAL_SECONDS=86400`).
Не нужна частая polling для slow-changing data.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.vault.models import VaultSecret
from src.workers.vault_reminders.metrics import (
    EMITTED_TOTAL,
    SCAN_DURATION_SECONDS,
    SCAN_ERRORS_TOTAL,
    SCAN_TOTAL,
)

logger = logging.getLogger(__name__)

SessionContextFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class VaultReminderWorker:
    """Daily reminder scanner."""

    def __init__(
        self,
        *,
        session_factory: SessionContextFactory,
        reminder_window_days: int = 7,
        scan_interval_seconds: float = 86400.0,
    ) -> None:
        """`reminder_window_days` — за сколько дней до expiry начинать
        напоминания. `scan_interval_seconds` — pause между сканами."""
        self._session_factory = session_factory
        self._window = timedelta(days=reminder_window_days)
        self._interval = scan_interval_seconds
        self._stop_event = asyncio.Event()

    def request_stop(self) -> None:
        logger.info("vault_reminder.stop_requested")
        self._stop_event.set()

    async def run_forever(self) -> None:
        """Main loop: scan, emit, sleep, repeat."""
        logger.info(
            "vault_reminder.start",
            extra={
                "window_days": self._window.days,
                "scan_interval_seconds": self._interval,
            },
        )
        while not self._stop_event.is_set():
            try:
                emitted = await self.run_once()
            except Exception:
                logger.exception("vault_reminder.scan_failed")
                SCAN_ERRORS_TOTAL.inc()
                emitted = 0
            logger.info("vault_reminder.scan_done", extra={"emitted": emitted})
            # Sleep с interruption на stop signal.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
        logger.info("vault_reminder.stopped")

    async def run_once(self) -> int:
        """Один scan tick. Returns count notifications emitted.

        Query: SELECT secrets WHERE archived_at IS NULL AND expires_at
        BETWEEN now AND now + window. Только active (non-archived).
        """
        SCAN_TOTAL.inc()
        started = time.perf_counter()
        try:
            async with self._session_factory() as session:
                now = datetime.now(UTC)
                deadline = now + self._window
                stmt = (
                    select(VaultSecret)
                    .where(
                        VaultSecret.archived_at.is_(None),
                        VaultSecret.expires_at.isnot(None),
                        VaultSecret.expires_at >= now,
                        VaultSecret.expires_at < deadline,
                    )
                    .order_by(VaultSecret.expires_at.asc())
                )
                result = await session.execute(stmt)
                rows = list(result.scalars().all())
                for secret in rows:
                    assert secret.expires_at is not None  # mypy guard
                    days_until = (secret.expires_at - now).days
                    logger.info(
                        "vault.reminder",
                        extra={
                            "secret_id": str(secret.id),
                            "owner_id": str(secret.owner_id),
                            "category": secret.category,
                            "days_until_expiry": days_until,
                            "expires_at": secret.expires_at.isoformat(),
                        },
                    )
                    EMITTED_TOTAL.labels(category=secret.category).inc()
                return len(rows)
        finally:
            SCAN_DURATION_SECONDS.observe(time.perf_counter() - started)


def install_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    worker: VaultReminderWorker,
) -> None:
    """SIGTERM/SIGINT → graceful shutdown (same pattern как indexer)."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, worker.request_stop)


__all__ = [
    "SessionContextFactory",
    "VaultReminderWorker",
    "install_signal_handlers",
]
