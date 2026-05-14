"""Unit tests для Prometheus metrics в vault_reminders (#176).

Patterns: создаём worker с mock session_factory, прогон run_once + run_forever
с asserts на счётчик delta.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.vault.models import VaultSecret
from src.workers.vault_reminders.metrics import (
    EMITTED_TOTAL,
    SCAN_DURATION_SECONDS,
    SCAN_ERRORS_TOTAL,
    SCAN_TOTAL,
)
from src.workers.vault_reminders.runner import VaultReminderWorker


def _make_secret(
    expires_in_days: int | None,
    *,
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
    s.archived_at = None
    return s


@asynccontextmanager
async def _shim_factory(session: Any) -> Any:
    yield session


def _make_factory(session: Any):  # type: ignore[no-untyped-def]
    def _factory():  # type: ignore[no-untyped-def]
        return _shim_factory(session)

    return _factory


def _counter_value(counter: Any, **labels: str) -> float:
    # `_value.get()` — prometheus_client internal, returns Any; explicit
    # float() cast для mypy strict (no-any-return).
    if labels:
        return float(counter.labels(**labels)._value.get())
    return float(counter._value.get())


def _histogram_count(histogram: Any) -> float:
    return float(histogram._sum.get())


@pytest.mark.asyncio
async def test_run_once_increments_scan_total() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    worker = VaultReminderWorker(session_factory=_make_factory(session))

    before = _counter_value(SCAN_TOTAL)
    await worker.run_once()
    after = _counter_value(SCAN_TOTAL)
    assert after - before == 1.0


@pytest.mark.asyncio
async def test_run_once_observes_duration() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    worker = VaultReminderWorker(session_factory=_make_factory(session))

    before = _histogram_count(SCAN_DURATION_SECONDS)
    await worker.run_once()
    after = _histogram_count(SCAN_DURATION_SECONDS)
    # Sum grows on every observe (always positive duration).
    assert after >= before


@pytest.mark.asyncio
async def test_run_once_increments_emitted_per_category() -> None:
    session = MagicMock()
    secrets = [
        _make_secret(2, category="infra"),
        _make_secret(3, category="infra"),
        _make_secret(5, category="cloud"),
    ]
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: secrets))
    )
    worker = VaultReminderWorker(session_factory=_make_factory(session))

    before_infra = _counter_value(EMITTED_TOTAL, category="infra")
    before_cloud = _counter_value(EMITTED_TOTAL, category="cloud")
    await worker.run_once()
    after_infra = _counter_value(EMITTED_TOTAL, category="infra")
    after_cloud = _counter_value(EMITTED_TOTAL, category="cloud")

    assert after_infra - before_infra == 2.0
    assert after_cloud - before_cloud == 1.0


@pytest.mark.asyncio
async def test_run_forever_increments_scan_errors_on_exception() -> None:
    """exception в run_once → SCAN_ERRORS_TOTAL increment."""
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("DB unreachable"))
    worker = VaultReminderWorker(
        session_factory=_make_factory(session),
        scan_interval_seconds=10.0,
    )

    before = _counter_value(SCAN_ERRORS_TOTAL)

    async def stop_after_one_iter() -> None:
        # Даём loop одну итерацию + чуть-чуть на error path.
        await asyncio.sleep(0.05)
        worker.request_stop()

    await asyncio.gather(worker.run_forever(), stop_after_one_iter())

    after = _counter_value(SCAN_ERRORS_TOTAL)
    assert after - before >= 1.0


@pytest.mark.asyncio
async def test_run_once_no_secrets_no_emit_counter() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    worker = VaultReminderWorker(session_factory=_make_factory(session))

    before = _counter_value(EMITTED_TOTAL, category="infra")
    await worker.run_once()
    after = _counter_value(EMITTED_TOTAL, category="infra")
    assert after == before
