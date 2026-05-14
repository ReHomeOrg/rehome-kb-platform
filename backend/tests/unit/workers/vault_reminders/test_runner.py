"""Unit tests для VaultReminderWorker (#167)."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from itertools import cycle
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.vault.models import VaultSecret
from src.workers.vault_reminders.runner import VaultReminderWorker


def _make_secret(
    expires_in_days: int | None,
    *,
    archived: bool = False,
    category: str = "infra",
) -> VaultSecret:
    s = VaultSecret()
    s.id = uuid4()
    s.title_ciphertext = b"opaque"
    s.category = category
    s.owner_id = uuid4()
    s.created_at = datetime.now(UTC)
    s.updated_at = datetime.now(UTC)
    s.expires_at = (
        datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days is not None else None
    )
    s.archived_at = datetime.now(UTC) if archived else None
    return s


@asynccontextmanager
async def _shim_factory(session: Any) -> Any:
    yield session


def _make_factory(session: Any):  # type: ignore[no-untyped-def]
    def _factory():  # type: ignore[no-untyped-def]
        return _shim_factory(session)

    return _factory


@pytest.mark.asyncio
async def test_run_once_emits_for_expiring_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Secrets within window emit log records."""
    session = MagicMock()
    secrets = [
        _make_secret(2, category="infra"),
        _make_secret(5, category="cloud"),
    ]
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: secrets))
    )
    worker = VaultReminderWorker(
        session_factory=_make_factory(session),
        reminder_window_days=7,
        scan_interval_seconds=0.01,
    )
    caplog.set_level(logging.INFO)
    emitted = await worker.run_once()
    assert emitted == 2
    # `vault.reminder` log record emitted per secret.
    reminders = [r for r in caplog.records if r.message == "vault.reminder"]
    assert len(reminders) == 2
    # Records содержат metadata fields.
    extras = [r.__dict__ for r in reminders]
    categories = {e.get("category") for e in extras}
    assert {"infra", "cloud"} <= categories


@pytest.mark.asyncio
async def test_run_once_zero_results() -> None:
    """Нет expiring secrets → return 0, no emit."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    worker = VaultReminderWorker(
        session_factory=_make_factory(session),
        reminder_window_days=7,
        scan_interval_seconds=0.01,
    )
    assert await worker.run_once() == 0


@pytest.mark.asyncio
async def test_run_once_filters_in_sql_query() -> None:
    """SQL contains expires_at + archived_at + window filters."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    worker = VaultReminderWorker(
        session_factory=_make_factory(session),
        reminder_window_days=7,
        scan_interval_seconds=0.01,
    )
    await worker.run_once()
    stmt = session.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    # `archived_at IS NULL` filter applied.
    assert "archived_at IS NULL" in compiled
    # `expires_at` range filter (>= now AND < deadline).
    assert "expires_at" in compiled


@pytest.mark.asyncio
async def test_run_forever_recovers_from_scan_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Scan exception → log + continue loop (no crash)."""
    session = MagicMock()
    # Alternate: first call raises, second returns empty.
    side_effects = cycle(
        [
            RuntimeError("DB down"),
            MagicMock(scalars=lambda: MagicMock(all=lambda: [])),
        ]
    )
    session.execute = AsyncMock(side_effect=lambda *_: next(side_effects))

    worker = VaultReminderWorker(
        session_factory=_make_factory(session),
        reminder_window_days=7,
        scan_interval_seconds=0.05,
    )
    caplog.set_level(logging.ERROR)

    async def _stop_soon() -> None:
        await asyncio.sleep(0.15)
        worker.request_stop()

    # Worker не должен бросать exception наружу.
    await asyncio.gather(worker.run_forever(), _stop_soon())
    # Хотя бы одна попытка scan'а была.
    assert session.execute.await_count >= 1


@pytest.mark.asyncio
async def test_request_stop_breaks_loop() -> None:
    """Stop event прерывает run_forever cleanly."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    worker = VaultReminderWorker(
        session_factory=_make_factory(session),
        reminder_window_days=7,
        scan_interval_seconds=0.05,
    )

    async def _stop_soon() -> None:
        await asyncio.sleep(0.1)
        worker.request_stop()

    await asyncio.gather(worker.run_forever(), _stop_soon())
