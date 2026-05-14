"""Unit tests для IndexerWorker (#149)."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.workers.indexer.runner import IndexerWorker


@asynccontextmanager
async def _shim_factory(session: Any) -> Any:
    """Mock session context — bypass'ит actual SQLAlchemy lifecycle."""
    yield session


def _make_session_factory(session: Any):  # type: ignore[no-untyped-def]
    def _factory():  # type: ignore[no-untyped-def]
        return _shim_factory(session)

    return _factory


def _stub_indexer(model_id: str = "mock-v1") -> MagicMock:
    """IndexerService stub с provider.model_id property."""
    indexer = MagicMock()
    indexer._provider = MagicMock(model_id=model_id)
    indexer.index_article = AsyncMock(return_value=3)  # 3 chunks indexed
    return indexer


@pytest.mark.asyncio
async def test_run_once_empty_returns_zero() -> None:
    """Нет pending articles → return 0, indexer не вызывается."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=iter([]))
    session.commit = AsyncMock()

    indexer = _stub_indexer()

    worker = IndexerWorker(
        session_factory=_make_session_factory(session),
        make_indexer=lambda _s: indexer,
        batch_size=10,
        poll_interval_seconds=0.01,
    )
    processed = await worker.run_once()
    assert processed == 0
    indexer.index_article.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_once_processes_batch() -> None:
    """Pending articles → каждый передан indexer'у."""
    session = MagicMock()
    article_ids = [uuid4(), uuid4(), uuid4()]
    # Simulate result iterator с row-like объектами.
    rows = [MagicMock(id=aid, body_markdown=f"body-{i}") for i, aid in enumerate(article_ids)]
    session.execute = AsyncMock(return_value=iter(rows))
    session.commit = AsyncMock()

    indexer = _stub_indexer()

    worker = IndexerWorker(
        session_factory=_make_session_factory(session),
        make_indexer=lambda _s: indexer,
        batch_size=10,
        poll_interval_seconds=0.01,
    )
    processed = await worker.run_once()
    assert processed == 3
    assert indexer.index_article.await_count == 3
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_once_continues_on_per_article_failure() -> None:
    """Один article failed → остальные обрабатываются; processed считает только успехи."""
    session = MagicMock()
    article_ids = [uuid4(), uuid4(), uuid4()]
    rows = [MagicMock(id=aid, body_markdown="body") for aid in article_ids]
    session.execute = AsyncMock(return_value=iter(rows))
    session.commit = AsyncMock()

    indexer = _stub_indexer()
    indexer.index_article = AsyncMock(side_effect=[2, RuntimeError("provider down"), 4])

    worker = IndexerWorker(
        session_factory=_make_session_factory(session),
        make_indexer=lambda _s: indexer,
        batch_size=10,
        poll_interval_seconds=0.01,
    )
    processed = await worker.run_once()
    # 2 successful (counts of 2 chunks and 4 chunks); 1 failed.
    assert processed == 2
    assert indexer.index_article.await_count == 3


@pytest.mark.asyncio
async def test_run_once_skips_zero_chunk_articles() -> None:
    """index_article возвращает 0 (empty body) → не counted в processed."""
    session = MagicMock()
    rows = [MagicMock(id=uuid4(), body_markdown="")]
    session.execute = AsyncMock(return_value=iter(rows))
    session.commit = AsyncMock()

    indexer = _stub_indexer()
    indexer.index_article = AsyncMock(return_value=0)  # empty body

    worker = IndexerWorker(
        session_factory=_make_session_factory(session),
        make_indexer=lambda _s: indexer,
        batch_size=10,
        poll_interval_seconds=0.01,
    )
    processed = await worker.run_once()
    assert processed == 0


@pytest.mark.asyncio
async def test_request_stop_breaks_run_forever() -> None:
    """stop_event прерывает loop."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=iter([]))
    session.commit = AsyncMock()

    worker = IndexerWorker(
        session_factory=_make_session_factory(session),
        make_indexer=lambda _s: _stub_indexer(),
        batch_size=10,
        poll_interval_seconds=0.05,  # короткий sleep
    )

    # Запускаем run_forever, через 100ms request_stop → должен exit.
    async def _stop_soon() -> None:
        await asyncio.sleep(0.1)
        worker.request_stop()

    await asyncio.gather(worker.run_forever(), _stop_soon())


@pytest.mark.asyncio
async def test_run_forever_recovers_from_batch_exception() -> None:
    """run_once бросает — run_forever логгирует и продолжает."""
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    session.commit = AsyncMock()

    call_count = 0

    def _make_indexer_counting(_s: Any) -> MagicMock:
        nonlocal call_count
        call_count += 1
        return _stub_indexer()

    worker = IndexerWorker(
        session_factory=_make_session_factory(session),
        make_indexer=_make_indexer_counting,
        batch_size=10,
        poll_interval_seconds=0.02,
    )

    async def _stop_soon() -> None:
        await asyncio.sleep(0.08)
        worker.request_stop()

    # run_forever не должен прокидывать exception наружу.
    await asyncio.gather(worker.run_forever(), _stop_soon())
    # Хотя бы одна попытка batch'а была.
    assert session.execute.await_count >= 1


@pytest.mark.asyncio
async def test_fetch_pending_uses_current_model_id() -> None:
    """Query фильтрует embeddings по provider.model_id."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=iter([]))
    session.commit = AsyncMock()

    indexer = _stub_indexer(model_id="hf-multilingual-e5-large-v2")

    worker = IndexerWorker(
        session_factory=_make_session_factory(session),
        make_indexer=lambda _s: indexer,
        batch_size=10,
        poll_interval_seconds=0.01,
    )
    await worker.run_once()
    session.execute.assert_awaited_once()
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[object] = []
    for v in compiled.params.values():
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    assert "hf-multilingual-e5-large-v2" in flat
    assert "PUBLISHED" in flat
