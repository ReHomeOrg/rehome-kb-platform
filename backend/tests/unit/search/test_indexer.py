"""Unit tests for IndexerService (#130)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.search.embeddings import MockEmbeddingProvider
from src.api.search.indexer import IndexerService


def _make_indexer(
    upsert_returns: int = 3,
    upsert_raises: Exception | None = None,
    delete_by_article_returns: int = 0,
    delete_by_slug_returns: int = 0,
    provider_raises: Exception | None = None,
) -> tuple[IndexerService, MagicMock, MagicMock]:
    """Indexer + mocked repo + mocked provider."""
    repo = MagicMock()
    repo.upsert = AsyncMock(side_effect=upsert_raises, return_value=upsert_returns)
    repo.delete_by_article = AsyncMock(return_value=delete_by_article_returns)
    repo.delete_by_article_slug = AsyncMock(return_value=delete_by_slug_returns)

    provider = MagicMock()
    provider.model_id = "test-model"
    if provider_raises is not None:
        provider.embed = AsyncMock(side_effect=provider_raises)
    else:
        provider.embed = AsyncMock(return_value=[[0.1] * 4 for _ in range(3)])

    return IndexerService(repo, provider), repo, provider


# ---------------------------------------------------------------------------
# index_article


@pytest.mark.asyncio
async def test_index_article_full_pipeline() -> None:
    indexer, repo, provider = _make_indexer(upsert_returns=2)
    n = await indexer.index_article(
        article_id=uuid4(),
        body_markdown="Para A.\n\nPara B.\n\nPara C.",
    )
    # 1 small text → 1 chunk → provider called → upsert called → returns n.
    provider.embed.assert_awaited_once()
    repo.upsert.assert_awaited_once()
    assert n == 2  # returned by mock repo


@pytest.mark.asyncio
async def test_index_article_empty_body_no_op() -> None:
    indexer, repo, provider = _make_indexer()
    n = await indexer.index_article(article_id=uuid4(), body_markdown="")
    assert n == 0
    provider.embed.assert_not_awaited()
    repo.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_article_whitespace_only_no_op() -> None:
    indexer, repo, provider = _make_indexer()
    n = await indexer.index_article(article_id=uuid4(), body_markdown="   \n\n  ")
    assert n == 0
    provider.embed.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_article_swallows_provider_error() -> None:
    """Provider failure logged, не пробрасывается (article transaction уже commit'нулась)."""
    indexer, repo, provider = _make_indexer(provider_raises=RuntimeError("boom"))
    n = await indexer.index_article(article_id=uuid4(), body_markdown="some text")
    assert n == 0
    repo.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_article_swallows_upsert_error() -> None:
    """Repo failure logged, не пробрасывается."""
    indexer, repo, provider = _make_indexer(upsert_raises=RuntimeError("db down"))
    n = await indexer.index_article(article_id=uuid4(), body_markdown="some text")
    assert n == 0


@pytest.mark.asyncio
async def test_index_article_uses_provider_model_id() -> None:
    indexer, repo, provider = _make_indexer()
    await indexer.index_article(article_id=uuid4(), body_markdown="text")
    kwargs = repo.upsert.call_args.kwargs
    assert kwargs["model_id"] == "test-model"


@pytest.mark.asyncio
async def test_index_article_real_mock_provider_integration() -> None:
    """End-to-end с MockEmbeddingProvider — никаких mocks."""
    repo = MagicMock()
    repo.upsert = AsyncMock(return_value=1)
    indexer = IndexerService(repo, MockEmbeddingProvider())
    n = await indexer.index_article(article_id=uuid4(), body_markdown="short")
    assert n == 1
    kwargs = repo.upsert.call_args.kwargs
    assert kwargs["model_id"] == "mock-v1"
    assert len(kwargs["embeddings"]) == len(kwargs["chunks"])


# ---------------------------------------------------------------------------
# remove_article + remove_article_by_slug


@pytest.mark.asyncio
async def test_remove_article_by_id() -> None:
    indexer, repo, _ = _make_indexer(delete_by_article_returns=5)
    n = await indexer.remove_article(uuid4())
    assert n == 5
    repo.delete_by_article.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_article_by_slug() -> None:
    indexer, repo, _ = _make_indexer(delete_by_slug_returns=3)
    n = await indexer.remove_article_by_slug("my-slug")
    assert n == 3
    repo.delete_by_article_slug.assert_awaited_once_with("my-slug")


@pytest.mark.asyncio
async def test_remove_article_swallows_errors() -> None:
    repo = MagicMock()
    repo.delete_by_article = AsyncMock(side_effect=RuntimeError("boom"))
    indexer = IndexerService(repo, MockEmbeddingProvider())
    n = await indexer.remove_article(uuid4())
    assert n == 0
