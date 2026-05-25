"""Unit tests для OutboxCleanupWorker (ADR-0026 Slice 4)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.outbox.cleanup_worker import OutboxCleanupWorker


class _FakeSessionCtx:
    def __init__(self) -> None:
        self.session = MagicMock()
        self.session.commit = AsyncMock()

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *args: Any) -> None:
        return None


def _settings(interval: float = 0.05, retention_days: int = 30) -> Any:
    s = MagicMock()
    s.outbox_cleanup_poll_interval_seconds = interval
    s.outbox_cleanup_retention_days = retention_days
    return s


def _factory() -> tuple[MagicMock, list[_FakeSessionCtx]]:
    sessions: list[_FakeSessionCtx] = []

    def _make() -> _FakeSessionCtx:
        ctx = _FakeSessionCtx()
        sessions.append(ctx)
        return ctx

    return MagicMock(side_effect=_make), sessions


def _patch_repo(monkeypatch: pytest.MonkeyPatch, *, delete_count: int) -> MagicMock:
    repo_cls = MagicMock()
    repo_instance = MagicMock()
    repo_instance.hard_delete_flushed = AsyncMock(return_value=delete_count)
    repo_cls.return_value = repo_instance
    monkeypatch.setattr("src.api.outbox.cleanup_worker.OutboxRepository", repo_cls)
    return repo_instance


@pytest.mark.asyncio
async def test_run_once_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, _ = _factory()
    repo = _patch_repo(monkeypatch, delete_count=0)
    worker = OutboxCleanupWorker(session_factory=factory, settings=_settings())
    assert await worker._run_once() == 0
    repo.hard_delete_flushed.assert_awaited_once()
    assert repo.hard_delete_flushed.call_args.kwargs["retention"].days == 30


@pytest.mark.asyncio
async def test_run_once_commits_on_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, sessions = _factory()
    _patch_repo(monkeypatch, delete_count=7)
    worker = OutboxCleanupWorker(session_factory=factory, settings=_settings())
    assert await worker._run_once() == 7
    sessions[0].session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_once_no_commit_on_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, sessions = _factory()
    _patch_repo(monkeypatch, delete_count=0)
    worker = OutboxCleanupWorker(session_factory=factory, settings=_settings())
    await worker._run_once()
    sessions[0].session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, _ = _factory()
    repo = _patch_repo(monkeypatch, delete_count=0)
    worker = OutboxCleanupWorker(session_factory=factory, settings=_settings(interval=0.05))
    worker.start()
    await asyncio.sleep(0.1)
    await worker.stop()
    assert repo.hard_delete_flushed.await_count >= 1


@pytest.mark.asyncio
async def test_loop_survives_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, _ = _factory()
    repo_cls = MagicMock()
    repo_instance = MagicMock()
    repo_instance.hard_delete_flushed = AsyncMock(side_effect=[RuntimeError("boom"), 0])
    repo_cls.return_value = repo_instance
    monkeypatch.setattr("src.api.outbox.cleanup_worker.OutboxRepository", repo_cls)
    worker = OutboxCleanupWorker(session_factory=factory, settings=_settings(interval=0.05))
    worker.start()
    await asyncio.sleep(0.2)
    await worker.stop()
    assert repo_instance.hard_delete_flushed.await_count >= 2
