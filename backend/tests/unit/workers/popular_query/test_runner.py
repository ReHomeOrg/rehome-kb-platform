"""Unit tests для PopularQueryWorker (#220, ТЗ §5.1)."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.search.query_log import PopularUnansweredQuery
from src.workers.popular_query.runner import PopularQueryWorker


@asynccontextmanager
async def _shim_factory(session: Any) -> Any:
    yield session


def _make_factory(session: Any):  # type: ignore[no-untyped-def]
    def _factory():  # type: ignore[no-untyped-def]
        return _shim_factory(session)

    return _factory


def _session_with(popular: list[PopularUnansweredQuery]) -> MagicMock:
    """Mock session где `SearchQueryLogRepository.find_popular_unanswered`
    intercept'ится через monkeypatching repo на module-level — но проще
    через AsyncMock на result set."""
    session = MagicMock()
    # Mock session.execute returns the SQL result (not used directly —
    # patch'им find_popular_unanswered ниже).
    session.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    session.commit = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_run_once_no_popular_queries_skips_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty result → return 0, no webhook dispatch, no commit."""
    session = _session_with([])
    monkeypatch.setattr(
        "src.workers.popular_query.runner.SearchQueryLogRepository.find_popular_unanswered",
        AsyncMock(return_value=[]),
    )
    dispatch_mock = AsyncMock(return_value=0)
    monkeypatch.setattr(
        "src.workers.popular_query.runner.WebhookEventDispatcher.dispatch",
        dispatch_mock,
    )

    worker = PopularQueryWorker(
        session_factory=_make_factory(session),
        window_hours=24,
        min_count=3,
    )
    emitted = await worker.run_once()
    assert emitted == 0
    dispatch_mock.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_once_dispatches_with_correct_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hot queries → dispatch с payload `{queries:[...], window_hours, min_count}`."""
    session = _session_with([])
    popular = [
        PopularUnansweredQuery(query="договор аренды", count=10),
        PopularUnansweredQuery(query="ипотека", count=5),
    ]
    monkeypatch.setattr(
        "src.workers.popular_query.runner.SearchQueryLogRepository.find_popular_unanswered",
        AsyncMock(return_value=popular),
    )
    dispatch_mock = AsyncMock(return_value=2)
    monkeypatch.setattr(
        "src.workers.popular_query.runner.WebhookEventDispatcher.dispatch",
        dispatch_mock,
    )

    worker = PopularQueryWorker(
        session_factory=_make_factory(session),
        window_hours=24,
        min_count=3,
    )
    emitted = await worker.run_once()
    assert emitted == 2

    dispatch_mock.assert_awaited_once()
    kwargs = dispatch_mock.call_args.kwargs
    assert kwargs["event_type"] == "search.popular_query"
    payload = kwargs["payload"]
    assert payload["queries"] == [
        {"query": "договор аренды", "count": 10},
        {"query": "ипотека", "count": 5},
    ]
    assert payload["window_hours"] == 24
    assert payload["min_count"] == 3
    # Session committed для persisting webhook_deliveries.
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_once_passes_config_to_aggregator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Custom config (window_hours, min_count, max_queries) пробрасывается."""
    session = _session_with([])
    find_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "src.workers.popular_query.runner.SearchQueryLogRepository.find_popular_unanswered",
        find_mock,
    )

    worker = PopularQueryWorker(
        session_factory=_make_factory(session),
        window_hours=12,
        min_count=5,
        max_queries=10,
    )
    await worker.run_once()

    find_mock.assert_awaited_once_with(window_hours=12, min_count=5, limit=10)


@pytest.mark.asyncio
async def test_run_forever_recovers_from_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Scan exception → log + continue loop (no crash)."""
    session = _session_with([])
    monkeypatch.setattr(
        "src.workers.popular_query.runner.SearchQueryLogRepository.find_popular_unanswered",
        AsyncMock(side_effect=RuntimeError("DB down")),
    )
    worker = PopularQueryWorker(
        session_factory=_make_factory(session),
        scan_interval_seconds=0.05,
    )

    async def _stop_soon() -> None:
        await asyncio.sleep(0.1)
        worker.request_stop()

    # Worker не должен бросать exception наружу.
    await asyncio.gather(worker.run_forever(), _stop_soon())


@pytest.mark.asyncio
async def test_request_stop_breaks_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _session_with([])
    monkeypatch.setattr(
        "src.workers.popular_query.runner.SearchQueryLogRepository.find_popular_unanswered",
        AsyncMock(return_value=[]),
    )
    worker = PopularQueryWorker(
        session_factory=_make_factory(session),
        scan_interval_seconds=0.05,
    )

    async def _stop_soon() -> None:
        await asyncio.sleep(0.1)
        worker.request_stop()

    await asyncio.gather(worker.run_forever(), _stop_soon())
