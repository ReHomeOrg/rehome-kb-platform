"""Unit tests для PD overdue worker (#340, ФЗ-152 §15)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.admin.pd_overdue_worker import PdOverdueWorker


class _FakeSessionCtx:
    """Async ctx-manager yielding mock session."""

    def __init__(self) -> None:
        self.session = MagicMock()
        self.session.commit = AsyncMock()

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *args: Any) -> None:
        return None


def _settings(interval: float = 0.05) -> Any:
    s = MagicMock()
    s.pd_overdue_worker_poll_interval_seconds = interval
    return s


def _factory_with_session() -> tuple[MagicMock, list[_FakeSessionCtx]]:
    sessions: list[_FakeSessionCtx] = []

    def _make() -> _FakeSessionCtx:
        ctx = _FakeSessionCtx()
        sessions.append(ctx)
        return ctx

    return MagicMock(side_effect=_make), sessions


@pytest.mark.asyncio
async def test_run_once_returns_zero_when_no_overdue(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, _ = _factory_with_session()
    repo_cls = MagicMock()
    repo_instance = MagicMock()
    repo_instance.mark_overdue = AsyncMock(return_value=0)
    repo_cls.return_value = repo_instance
    monkeypatch.setattr("src.api.admin.pd_overdue_worker.PersonalDataRequestRepository", repo_cls)

    worker = PdOverdueWorker(session_factory=factory, settings=_settings())
    count = await worker._run_once()
    assert count == 0
    repo_instance.mark_overdue.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_once_commits_when_rows_transitioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, sessions = _factory_with_session()
    repo_cls = MagicMock()
    repo_instance = MagicMock()
    repo_instance.mark_overdue = AsyncMock(return_value=3)
    repo_cls.return_value = repo_instance
    monkeypatch.setattr("src.api.admin.pd_overdue_worker.PersonalDataRequestRepository", repo_cls)

    worker = PdOverdueWorker(session_factory=factory, settings=_settings())
    count = await worker._run_once()
    assert count == 3
    sessions[0].session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_once_does_not_commit_when_zero_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Idle iteration — no commit (avoid empty transaction overhead)."""
    factory, sessions = _factory_with_session()
    repo_cls = MagicMock()
    repo_instance = MagicMock()
    repo_instance.mark_overdue = AsyncMock(return_value=0)
    repo_cls.return_value = repo_instance
    monkeypatch.setattr("src.api.admin.pd_overdue_worker.PersonalDataRequestRepository", repo_cls)

    worker = PdOverdueWorker(session_factory=factory, settings=_settings())
    await worker._run_once()
    sessions[0].session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_stop_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker создаёт task на start, stops gracefully on stop."""
    factory, _ = _factory_with_session()
    repo_cls = MagicMock()
    repo_instance = MagicMock()
    repo_instance.mark_overdue = AsyncMock(return_value=0)
    repo_cls.return_value = repo_instance
    monkeypatch.setattr("src.api.admin.pd_overdue_worker.PersonalDataRequestRepository", repo_cls)

    worker = PdOverdueWorker(session_factory=factory, settings=_settings(interval=0.05))
    worker.start()
    assert worker._task is not None
    # Allow at least one iteration.
    await asyncio.sleep(0.1)
    await worker.stop()
    assert worker._task is None
    # mark_overdue was called at least once.
    assert repo_instance.mark_overdue.await_count >= 1


@pytest.mark.asyncio
async def test_start_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Двойной start — single task."""
    factory, _ = _factory_with_session()
    repo_cls = MagicMock()
    repo_instance = MagicMock()
    repo_instance.mark_overdue = AsyncMock(return_value=0)
    repo_cls.return_value = repo_instance
    monkeypatch.setattr("src.api.admin.pd_overdue_worker.PersonalDataRequestRepository", repo_cls)

    worker = PdOverdueWorker(session_factory=factory, settings=_settings())
    worker.start()
    first_task = worker._task
    worker.start()
    assert worker._task is first_task
    await worker.stop()


@pytest.mark.asyncio
async def test_loop_survives_iteration_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если mark_overdue raises — worker не падает, logs + retries."""
    factory, _ = _factory_with_session()
    repo_cls = MagicMock()
    repo_instance = MagicMock()
    # First call raises, second returns 0.
    repo_instance.mark_overdue = AsyncMock(side_effect=[RuntimeError("db down"), 0])
    repo_cls.return_value = repo_instance
    monkeypatch.setattr("src.api.admin.pd_overdue_worker.PersonalDataRequestRepository", repo_cls)

    worker = PdOverdueWorker(session_factory=factory, settings=_settings(interval=0.05))
    worker.start()
    await asyncio.sleep(0.2)  # Allow ≥2 iterations.
    await worker.stop()
    # mark_overdue called multiple times — worker survived exception.
    assert repo_instance.mark_overdue.await_count >= 2
