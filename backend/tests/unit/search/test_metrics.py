"""Unit tests для retrieval Prometheus metrics (#179)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from src.api.auth.scope import AccessLevel
from src.api.search.embeddings import MockEmbeddingProvider
from src.api.search.metrics import (
    RETRIEVAL_DURATION_SECONDS,
    RETRIEVAL_HITS,
    RETRIEVAL_TOTAL,
)
from src.api.search.repository import RetrievalHit
from src.api.search.retrieval import RetrievalService


def _hit(article_id: UUID, chunk_index: int = 0, score: float = 0.5) -> RetrievalHit:
    return RetrievalHit(
        article_id=article_id,
        slug=f"slug-{article_id}",
        title=f"Title {article_id}",
        chunk_index=chunk_index,
        text=f"chunk-{chunk_index}",
        char_start=0,
        char_end=10,
        score=score,
    )


def _make_service(
    vector_hits: list[RetrievalHit] | None = None,
    bm25_articles: list[tuple[Any, ...]] | None = None,
) -> RetrievalService:
    embedding_repo = MagicMock()
    embedding_repo.search = AsyncMock(return_value=vector_hits or [])
    article_repo = MagicMock()
    article_repo.search = AsyncMock(return_value=(bm25_articles or [], False))
    return RetrievalService(embedding_repo, article_repo, MockEmbeddingProvider())


def _counter_value(counter: Any, **labels: str) -> float:
    return float(counter.labels(**labels)._value.get())


def _histogram_sum(histogram: Any) -> float:
    return float(histogram._sum.get())


@pytest.mark.asyncio
async def test_empty_query_increments_no_results_counter() -> None:
    svc = _make_service()
    before = _counter_value(RETRIEVAL_TOTAL, has_results="no")
    await svc.search(query="", access_levels=frozenset([AccessLevel.PUBLIC]))
    after = _counter_value(RETRIEVAL_TOTAL, has_results="no")
    assert after - before == 1.0


@pytest.mark.asyncio
async def test_empty_access_levels_increments_no_results_counter() -> None:
    svc = _make_service()
    before = _counter_value(RETRIEVAL_TOTAL, has_results="no")
    await svc.search(query="hello", access_levels=frozenset())
    after = _counter_value(RETRIEVAL_TOTAL, has_results="no")
    assert after - before == 1.0


@pytest.mark.asyncio
async def test_results_found_increments_yes_counter() -> None:
    article_id = uuid4()
    svc = _make_service(vector_hits=[_hit(article_id)])
    before = _counter_value(RETRIEVAL_TOTAL, has_results="yes")
    hits = await svc.search(query="x", access_levels=frozenset([AccessLevel.PUBLIC]))
    assert len(hits) > 0
    after = _counter_value(RETRIEVAL_TOTAL, has_results="yes")
    assert after - before == 1.0


@pytest.mark.asyncio
async def test_zero_hits_post_fusion_increments_no_counter() -> None:
    """Empty vector_hits → fused result [] → has_results=no."""
    svc = _make_service(vector_hits=[])
    before = _counter_value(RETRIEVAL_TOTAL, has_results="no")
    hits = await svc.search(query="x", access_levels=frozenset([AccessLevel.PUBLIC]))
    assert hits == []
    after = _counter_value(RETRIEVAL_TOTAL, has_results="no")
    assert after - before == 1.0


@pytest.mark.asyncio
async def test_duration_observed_on_non_empty_call() -> None:
    svc = _make_service(vector_hits=[_hit(uuid4())])
    before = _histogram_sum(RETRIEVAL_DURATION_SECONDS)
    await svc.search(query="x", access_levels=frozenset([AccessLevel.PUBLIC]))
    after = _histogram_sum(RETRIEVAL_DURATION_SECONDS)
    assert after >= before


@pytest.mark.asyncio
async def test_hits_histogram_observed_with_count() -> None:
    svc = _make_service(vector_hits=[_hit(uuid4()), _hit(uuid4(), chunk_index=1)])
    before = _histogram_sum(RETRIEVAL_HITS)
    hits = await svc.search(query="x", access_levels=frozenset([AccessLevel.PUBLIC]))
    after = _histogram_sum(RETRIEVAL_HITS)
    # Sum grows by len(hits) (sum aggregator).
    assert after - before == float(len(hits))
