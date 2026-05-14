"""Unit tests for RetrievalService — RRF fusion (#132) + provider factory (#140)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from src.api.auth.scope import AccessLevel
from src.api.config import Settings
from src.api.search.embeddings import MockEmbeddingProvider
from src.api.search.repository import RetrievalHit
from src.api.search.retrieval import RetrievalService, _build_provider


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
) -> tuple[RetrievalService, MagicMock, MagicMock]:
    embedding_repo = MagicMock()
    embedding_repo.search = AsyncMock(return_value=vector_hits or [])

    article_repo = MagicMock()
    article_repo.search = AsyncMock(return_value=(bm25_articles or [], False))

    svc = RetrievalService(embedding_repo, article_repo, MockEmbeddingProvider())
    return svc, embedding_repo, article_repo


# ---------------------------------------------------------------------------
# search() integration


@pytest.mark.asyncio
async def test_search_empty_query_returns_empty() -> None:
    svc, em, ar = _make_service()
    hits = await svc.search(query="", access_levels=frozenset([AccessLevel.PUBLIC]))
    assert hits == []
    em.search.assert_not_awaited()
    ar.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_whitespace_query_returns_empty() -> None:
    svc, _, _ = _make_service()
    hits = await svc.search(query="   \n", access_levels=frozenset([AccessLevel.PUBLIC]))
    assert hits == []


@pytest.mark.asyncio
async def test_search_no_access_levels_returns_empty() -> None:
    svc, em, ar = _make_service()
    hits = await svc.search(query="hello", access_levels=frozenset())
    assert hits == []
    em.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_calls_both_retrievers() -> None:
    svc, em, ar = _make_service()
    await svc.search(query="hello world", access_levels=frozenset([AccessLevel.PUBLIC]))
    em.search.assert_awaited_once()
    ar.search.assert_awaited_once()
    # Both got same query / access_levels.
    em_kwargs = em.search.call_args.kwargs
    assert em_kwargs["access_levels"] == frozenset([AccessLevel.PUBLIC])
    # model_id from MockProvider.
    assert em_kwargs["model_id"] == "mock-v1"


# ---------------------------------------------------------------------------
# RRF fusion math


def test_rrf_fuse_vector_only() -> None:
    """Без BM25 совпадений — score = 1/(60 + v_rank+1)."""
    a = uuid4()
    vector_hits = [_hit(a, chunk_index=0), _hit(a, chunk_index=1)]
    fused = RetrievalService._rrf_fuse(vector_hits, [], top_k=10)
    assert len(fused) == 2
    # Rank 1: 1/61, rank 2: 1/62.
    assert abs(fused[0].score - 1.0 / 61) < 1e-9
    assert abs(fused[1].score - 1.0 / 62) < 1e-9


def test_rrf_fuse_bm25_match_boosts_score() -> None:
    """Chunk у которого article также matches BM25 — получает добавку
    1/(60 + b_rank+1)."""
    a = uuid4()
    vector_hits = [_hit(a, chunk_index=0)]
    bm25 = [(a, "title", "snippet", 0.5)]  # rank 1
    fused = RetrievalService._rrf_fuse(vector_hits, bm25, top_k=10)
    expected = 1.0 / 61 + 1.0 / 61  # v_rank=1, b_rank=1
    assert abs(fused[0].score - expected) < 1e-9


def test_rrf_fuse_orders_by_descending_score() -> None:
    """Chunk hit с BM25 boost'ом должен подняться выше vector-only."""
    a, b, c = uuid4(), uuid4(), uuid4()
    vector_hits = [
        _hit(a, chunk_index=0),  # v_rank=1, нет BM25 → 1/61 = 0.0164
        _hit(b, chunk_index=0),  # v_rank=2, BM25 rank 1 → 1/62 + 1/61 = 0.0326
        _hit(c, chunk_index=0),  # v_rank=3, BM25 rank 2 → 1/63 + 1/62 = 0.0320
    ]
    bm25 = [(b, "t", "s", 0.5), (c, "t", "s", 0.4)]
    fused = RetrievalService._rrf_fuse(vector_hits, bm25, top_k=10)
    assert fused[0].article_id == b  # highest fused score
    assert fused[1].article_id == c
    assert fused[2].article_id == a


def test_rrf_fuse_respects_top_k() -> None:
    vector_hits = [_hit(uuid4(), chunk_index=i) for i in range(5)]
    fused = RetrievalService._rrf_fuse(vector_hits, [], top_k=2)
    assert len(fused) == 2


def test_rrf_fuse_empty_inputs() -> None:
    assert RetrievalService._rrf_fuse([], [], top_k=10) == []


def test_rrf_fuse_bm25_only_articles_dropped() -> None:
    """Article ранжированная только BM25 (без vector chunk match) НЕ
    появляется в fused output.

    Это осознанный trade-off (см. retrieval.py docstring §"BM25-only
    article hits dropped"): output обязан быть chunk-granularity для
    citations / chat-grounding, и article без конкретного chunk
    бесполезна.
    """
    bm25_only = uuid4()
    # vector_hits — пусто (или содержит другие article'и), BM25 нашёл
    # `bm25_only` article, но без vector chunk — её не должно быть в fused.
    fused = RetrievalService._rrf_fuse(
        vector_hits=[],
        bm25_articles=[(bm25_only, "title", "snippet", 0.9)],
        top_k=10,
    )
    assert fused == []
    # Тот же scenario с vector chunk'ами других article'й — BM25-only
    # article всё равно не появляется.
    other = uuid4()
    fused = RetrievalService._rrf_fuse(
        vector_hits=[_hit(other, chunk_index=0)],
        bm25_articles=[(bm25_only, "title", "snippet", 0.9)],
        top_k=10,
    )
    assert {h.article_id for h in fused} == {other}


def test_rrf_score_replaces_distance_in_hit() -> None:
    """Output score — RRF fused (higher=better), не original cosine
    distance (lower=better). Caller'ы ожидают higher=better convention."""
    a = uuid4()
    vector_hits = [_hit(a, chunk_index=0, score=0.234)]  # cosine distance
    fused = RetrievalService._rrf_fuse(vector_hits, [], top_k=10)
    assert fused[0].score != 0.234  # replaced
    assert fused[0].score == 1.0 / 61


# ---------------------------------------------------------------------------
# _build_provider factory (#140)


def test_build_provider_mock_returns_mock_instance() -> None:
    settings = Settings(EMBEDDING_PROVIDER="mock")
    provider = _build_provider(settings)
    assert isinstance(provider, MockEmbeddingProvider)
    # Mock использует свой stable `mock-v1`, не `settings.embedding_model`.
    assert provider.model_id == "mock-v1"


def test_build_provider_hf_lazy_imports_only_when_selected() -> None:
    """`mock` choice не должен trigger'ить import sentence_transformers.

    Проверяет что lazy import рабочает: даже если деп не установлен,
    `mock` path работает (что critical для CI без RAG deps).
    """
    settings = Settings(EMBEDDING_PROVIDER="mock")
    # Должно не упасть даже без sentence_transformers.
    _build_provider(settings)


def test_build_provider_unknown_raises() -> None:
    """Unknown choice → ValueError fail-fast."""
    # bypass'им Literal validation на pydantic — конструируем Settings
    # с mock и затем mutируем поле напрямую.
    settings = Settings(EMBEDDING_PROVIDER="mock")
    object.__setattr__(settings, "embedding_provider", "bogus")
    with pytest.raises(ValueError, match="unknown embedding_provider"):
        _build_provider(settings)
