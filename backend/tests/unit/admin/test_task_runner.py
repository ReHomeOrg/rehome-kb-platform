"""Unit tests для AdminTaskRunner (#268, ADR-0020 B).

Tests background coroutine execution paths (_run_*):
- success path → mark_running → work → mark_completed → commit
- failure path → rollback → mark_failed_isolated
- domain-specific branches (e.g. reindex documents skips indexer)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.api.admin.task_runner import (
    AdminTaskRunner,
    get_admin_task_runner,
    init_runner,
)


class _FakeSessionContext:
    """Async context manager returning a MagicMock session."""

    def __init__(self) -> None:
        self.session = MagicMock()
        self.session.commit = AsyncMock()
        self.session.rollback = AsyncMock()

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *args: Any) -> None:
        return None


def _make_session_factory() -> tuple[MagicMock, list[Any]]:
    """Returns (factory_callable, [sessions]). Each call yields fresh ctx."""
    sessions: list[_FakeSessionContext] = []

    def _factory() -> _FakeSessionContext:
        ctx = _FakeSessionContext()
        sessions.append(ctx)
        return ctx

    factory = MagicMock(side_effect=_factory)
    return factory, sessions


@pytest.fixture
def runner_with_mocks() -> tuple[AdminTaskRunner, MagicMock, list[Any]]:
    """AdminTaskRunner с mocked session_factory."""
    factory, sessions = _make_session_factory()
    settings = MagicMock()
    runner = AdminTaskRunner(session_factory=factory, settings=settings)
    return runner, factory, sessions


# ---------------------------------------------------------------------------
# Singleton init / get
# ---------------------------------------------------------------------------


def test_get_admin_task_runner_raises_if_uninitialized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.api.admin.task_runner._RUNNER", None)
    with pytest.raises(RuntimeError, match="not initialized"):
        get_admin_task_runner()


def test_init_runner_replaces_singleton() -> None:
    factory = MagicMock()
    settings = MagicMock()
    r1 = init_runner(factory, settings)
    r2 = init_runner(factory, settings)
    assert r1 is not r2
    # After init, get returns the latest singleton.
    assert get_admin_task_runner() is r2


# ---------------------------------------------------------------------------
# Reindex
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_reindex_articles_success(
    runner_with_mocks: tuple[AdminTaskRunner, MagicMock, list[Any]],
) -> None:
    """scope=articles → mark_running → indexer.reindex_all_articles → mark_completed → commit."""
    runner, factory, sessions = runner_with_mocks
    task_id = uuid4()

    repo = MagicMock()
    repo.mark_running = AsyncMock()
    repo.mark_completed = AsyncMock()
    repo.mark_failed = AsyncMock()

    indexer = MagicMock()
    indexer.reindex_all_articles = AsyncMock(
        return_value=MagicMock(articles_processed=5, chunks_total=15, errors_total=0)
    )

    with (
        patch("src.api.admin.task_runner.AdminTaskRepository", return_value=repo),
        patch("src.api.admin.task_runner.ArticleRepository"),
        patch("src.api.admin.task_runner._build_indexer", return_value=indexer),
    ):
        await runner._run_reindex(task_id, "articles", "admin-uuid")

    repo.mark_running.assert_awaited_once_with(task_id)
    indexer.reindex_all_articles.assert_awaited_once()
    repo.mark_completed.assert_awaited_once_with(task_id)
    repo.mark_failed.assert_not_awaited()
    sessions[0].session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_reindex_documents_skips_indexer(
    runner_with_mocks: tuple[AdminTaskRunner, MagicMock, list[Any]],
) -> None:
    """scope=documents — honest stub, no indexer call, COMPLETED."""
    runner, _factory, sessions = runner_with_mocks
    task_id = uuid4()

    repo = MagicMock()
    repo.mark_running = AsyncMock()
    repo.mark_completed = AsyncMock()

    indexer = MagicMock()
    indexer.reindex_all_articles = AsyncMock()

    with (
        patch("src.api.admin.task_runner.AdminTaskRepository", return_value=repo),
        patch("src.api.admin.task_runner._build_indexer", return_value=indexer),
    ):
        await runner._run_reindex(task_id, "documents", "admin-uuid")

    repo.mark_running.assert_awaited_once_with(task_id)
    indexer.reindex_all_articles.assert_not_awaited()
    repo.mark_completed.assert_awaited_once_with(task_id)
    sessions[0].session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_reindex_zero_processed_with_errors_marks_failed(
    runner_with_mocks: tuple[AdminTaskRunner, MagicMock, list[Any]],
) -> None:
    """0 processed + errors > 0 → mark_failed без mark_completed."""
    runner, _factory, sessions = runner_with_mocks
    task_id = uuid4()

    repo = MagicMock()
    repo.mark_running = AsyncMock()
    repo.mark_completed = AsyncMock()
    repo.mark_failed = AsyncMock()

    indexer = MagicMock()
    indexer.reindex_all_articles = AsyncMock(
        return_value=MagicMock(articles_processed=0, chunks_total=0, errors_total=3)
    )

    with (
        patch("src.api.admin.task_runner.AdminTaskRepository", return_value=repo),
        patch("src.api.admin.task_runner.ArticleRepository"),
        patch("src.api.admin.task_runner._build_indexer", return_value=indexer),
    ):
        await runner._run_reindex(task_id, "articles", "admin-uuid")

    repo.mark_failed.assert_awaited_once()
    args, kwargs = repo.mark_failed.call_args
    assert args[0] == task_id
    assert "3 article(s) failed" in kwargs["error"]
    repo.mark_completed.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_reindex_exception_rolls_back_and_isolates_failure(
    runner_with_mocks: tuple[AdminTaskRunner, MagicMock, list[Any]],
) -> None:
    """Unhandled exception → rollback + fresh-session mark_failed."""
    runner, factory, sessions = runner_with_mocks
    task_id = uuid4()

    main_repo = MagicMock()
    main_repo.mark_running = AsyncMock(side_effect=RuntimeError("boom"))
    main_repo.mark_failed = AsyncMock()

    # Second AdminTaskRepository instantiation (inside _mark_failed_isolated)
    # gets its own mock with mark_failed.
    isolated_repo = MagicMock()
    isolated_repo.mark_failed = AsyncMock()

    repo_class_mock = MagicMock(side_effect=[main_repo, isolated_repo])

    with patch("src.api.admin.task_runner.AdminTaskRepository", repo_class_mock):
        await runner._run_reindex(task_id, "articles", "admin-uuid")

    # Outer session rolled back.
    sessions[0].session.rollback.assert_awaited_once()
    sessions[0].session.commit.assert_not_awaited()
    # Fresh session opened for failure marking.
    assert factory.call_count == 2
    isolated_repo.mark_failed.assert_awaited_once()
    iso_call = isolated_repo.mark_failed.call_args
    assert iso_call.args[0] == task_id
    assert "boom" in iso_call.kwargs["error"]
    sessions[1].session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# Audit-log export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_audit_export_success(
    runner_with_mocks: tuple[AdminTaskRunner, MagicMock, list[Any]],
) -> None:
    """mark_running → mark_completed(result_url=...) → commit."""
    runner, _factory, sessions = runner_with_mocks
    task_id = uuid4()
    result_url = "/api/v1/audit-log/export.csv?since=2026-05-01"

    repo = MagicMock()
    repo.mark_running = AsyncMock()
    repo.mark_completed = AsyncMock()

    with patch("src.api.admin.task_runner.AdminTaskRepository", return_value=repo):
        await runner._run_audit_export(task_id, result_url, "admin-uuid")

    repo.mark_running.assert_awaited_once_with(task_id)
    repo.mark_completed.assert_awaited_once_with(task_id, result_url=result_url)
    sessions[0].session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_audit_export_exception_marks_failed(
    runner_with_mocks: tuple[AdminTaskRunner, MagicMock, list[Any]],
) -> None:
    runner, factory, sessions = runner_with_mocks
    task_id = uuid4()

    main_repo = MagicMock()
    main_repo.mark_running = AsyncMock(side_effect=RuntimeError("io_error"))

    isolated_repo = MagicMock()
    isolated_repo.mark_failed = AsyncMock()

    repo_class_mock = MagicMock(side_effect=[main_repo, isolated_repo])

    with patch("src.api.admin.task_runner.AdminTaskRepository", repo_class_mock):
        await runner._run_audit_export(task_id, "/path", "admin-uuid")

    sessions[0].session.rollback.assert_awaited_once()
    isolated_repo.mark_failed.assert_awaited_once()
    assert "io_error" in isolated_repo.mark_failed.call_args.kwargs["error"]


# ---------------------------------------------------------------------------
# Eval-run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_eval_success_stores_results_in_params(
    runner_with_mocks: tuple[AdminTaskRunner, MagicMock, list[Any]],
) -> None:
    """Eval execution → results stored inline в task.params['results']."""
    runner, _factory, sessions = runner_with_mocks
    task_id = uuid4()

    task_row = MagicMock()
    task_row.params = {"providers": ["mock"], "test_set": "smoke"}

    repo = MagicMock()
    repo.mark_running = AsyncMock()
    repo.mark_completed = AsyncMock()
    repo.get = AsyncMock(return_value=task_row)

    # Mock pair_results / aggregate_results returning predictable shape.
    fake_agg = MagicMock(
        composite_avg=0.8,
        citation_accuracy_avg=0.9,
        latency_p50=0.123,
        cost_per_query_avg=0.05,
    )
    judge_metrics = {
        "answer_correctness": 0.85,
        "faithfulness": None,
        "refusal_correctness": 0.95,
    }

    with (
        patch("src.api.admin.task_runner.AdminTaskRepository", return_value=repo),
        patch("src.eval.runner.run_dataset", new=AsyncMock(return_value=[])),
        patch("src.eval.report.aggregate_results", return_value=fake_agg),
        patch(
            "src.api.admin.eval_runs_service._aggregate_judge_metrics",
            return_value=judge_metrics,
        ),
    ):
        await runner._run_eval(task_id, ["mock"], pairs=[], actor_sub="admin-uuid")

    repo.mark_running.assert_awaited_once_with(task_id)
    repo.mark_completed.assert_awaited_once_with(task_id)
    assert "results" in task_row.params
    assert len(task_row.params["results"]) == 1
    assert task_row.params["results"][0]["provider"] == "mock"
    assert task_row.params["results"][0]["composite_score"] == 0.8
    sessions[0].session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_eval_exception_marks_failed(
    runner_with_mocks: tuple[AdminTaskRunner, MagicMock, list[Any]],
) -> None:
    runner, _factory, sessions = runner_with_mocks
    task_id = uuid4()

    main_repo = MagicMock()
    main_repo.mark_running = AsyncMock(side_effect=RuntimeError("eval_crash"))

    isolated_repo = MagicMock()
    isolated_repo.mark_failed = AsyncMock()

    repo_class_mock = MagicMock(side_effect=[main_repo, isolated_repo])

    with patch("src.api.admin.task_runner.AdminTaskRepository", repo_class_mock):
        await runner._run_eval(task_id, ["mock"], [], "admin-uuid")

    sessions[0].session.rollback.assert_awaited_once()
    isolated_repo.mark_failed.assert_awaited_once()
    assert "eval_crash" in isolated_repo.mark_failed.call_args.kwargs["error"]


# ---------------------------------------------------------------------------
# Spawn returns Task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_reindex_returns_asyncio_task(
    runner_with_mocks: tuple[AdminTaskRunner, MagicMock, list[Any]],
) -> None:
    import asyncio

    runner, _factory, _sessions = runner_with_mocks
    task_id = uuid4()

    repo = MagicMock()
    repo.mark_running = AsyncMock()
    repo.mark_completed = AsyncMock()

    indexer = MagicMock()
    indexer.reindex_all_articles = AsyncMock(
        return_value=MagicMock(articles_processed=0, chunks_total=0, errors_total=0)
    )

    with (
        patch("src.api.admin.task_runner.AdminTaskRepository", return_value=repo),
        patch("src.api.admin.task_runner.ArticleRepository"),
        patch("src.api.admin.task_runner._build_indexer", return_value=indexer),
    ):
        task = runner.spawn_reindex(task_id, "all", "admin-uuid")
        assert isinstance(task, asyncio.Task)
        await task  # ensure no unhandled exception
