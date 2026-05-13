"""Unit tests for EmbeddingRepository (#128)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.search.chunker import Chunk
from src.api.search.repository import EmbeddingRepository


def _session() -> MagicMock:
    s = MagicMock()
    exec_result = MagicMock(rowcount=3)
    s.execute = AsyncMock(return_value=exec_result)
    s.flush = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_upsert_empty_returns_zero() -> None:
    repo = EmbeddingRepository(_session())
    n = await repo.upsert(
        article_id=uuid4(),
        chunks=[],
        embeddings=[],
        model_id="m",
    )
    assert n == 0


@pytest.mark.asyncio
async def test_upsert_length_mismatch_raises() -> None:
    repo = EmbeddingRepository(_session())
    with pytest.raises(ValueError, match="length mismatch"):
        await repo.upsert(
            article_id=uuid4(),
            chunks=[Chunk("x", 0, 1)],
            embeddings=[[1.0], [2.0]],
            model_id="m",
        )


@pytest.mark.asyncio
async def test_upsert_executes_insert_and_returns_count() -> None:
    session = _session()
    repo = EmbeddingRepository(session)
    chunks = [Chunk(text=f"c{i}", char_start=i * 10, char_end=(i + 1) * 10) for i in range(3)]
    embeddings = [[0.1] * 4 for _ in range(3)]
    n = await repo.upsert(
        article_id=uuid4(),
        chunks=chunks,
        embeddings=embeddings,
        model_id="mock-v1",
    )
    assert n == 3
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_by_article() -> None:
    session = _session()
    repo = EmbeddingRepository(session)
    n = await repo.delete_by_article(uuid4())
    # rowcount=3 из _session mock
    assert n == 3
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_by_model() -> None:
    session = _session()
    repo = EmbeddingRepository(session)
    n = await repo.delete_by_model("old-model-id")
    assert n == 3
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_handles_none_rowcount() -> None:
    """SQLAlchemy в некоторых case'ах возвращает rowcount=None."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=None))
    session.flush = AsyncMock()
    repo = EmbeddingRepository(session)
    n = await repo.delete_by_article(uuid4())
    assert n == 0
