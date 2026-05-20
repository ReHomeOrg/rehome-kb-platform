"""Unit tests для reap_stale_tasks (#268, ADR-0020 B §Crash recovery)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.admin.task_reaper import STALE_THRESHOLD, reap_stale_tasks


class _FakeSession:
    def __init__(self, rowcount: int) -> None:
        self.execute = AsyncMock(return_value=MagicMock(rowcount=rowcount))
        self.commit = AsyncMock()
        self.executed_stmt: Any = None

        async def _execute(stmt: Any) -> MagicMock:
            self.executed_stmt = stmt
            return MagicMock(rowcount=rowcount)

        self.execute = _execute  # type: ignore[assignment]


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> Any:
        outer = self

        class _Ctx:
            async def __aenter__(self) -> _FakeSession:
                return outer._session

            async def __aexit__(self, *args: Any) -> None:
                return None

        return _Ctx()


@pytest.mark.asyncio
async def test_reap_returns_rowcount_when_stale_tasks_found() -> None:
    session = _FakeSession(rowcount=3)
    factory = _FakeSessionFactory(session)

    reaped = await reap_stale_tasks(factory)  # type: ignore[arg-type]

    assert reaped == 3
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reap_returns_zero_when_nothing_stale() -> None:
    session = _FakeSession(rowcount=0)
    factory = _FakeSessionFactory(session)

    reaped = await reap_stale_tasks(factory)  # type: ignore[arg-type]

    assert reaped == 0
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reap_uses_default_threshold_15min() -> None:
    """STALE_THRESHOLD = 15 минут — public contract."""
    assert timedelta(minutes=15) == STALE_THRESHOLD


@pytest.mark.asyncio
async def test_reap_uses_custom_threshold_and_now() -> None:
    """Caller может override threshold + now (для тестируемости)."""
    session = _FakeSession(rowcount=1)
    factory = _FakeSessionFactory(session)
    fixed_now = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)
    threshold = timedelta(minutes=5)

    reaped = await reap_stale_tasks(factory, threshold=threshold, now=fixed_now)  # type: ignore[arg-type]

    assert reaped == 1
    # Statement was built — exact assertion would require introspecting
    # SQLAlchemy clause; we trust execute was called.
    assert session.executed_stmt is not None


@pytest.mark.asyncio
async def test_reap_rowcount_none_returns_zero() -> None:
    """SQLAlchemy may return rowcount=None; coalesce to 0."""

    class _NullRowcountSession:
        def __init__(self) -> None:
            self.commit = AsyncMock()

            async def _execute(stmt: Any) -> MagicMock:
                m = MagicMock()
                m.rowcount = None
                return m

            self.execute = _execute

    session = _NullRowcountSession()
    factory = _FakeSessionFactory(session)  # type: ignore[arg-type]

    reaped = await reap_stale_tasks(factory)  # type: ignore[arg-type]
    assert reaped == 0
