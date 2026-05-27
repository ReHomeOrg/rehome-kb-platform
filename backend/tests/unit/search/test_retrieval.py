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
    bm25 = [(a, "slug-a", "title", "snippet", 0.5)]  # rank 1
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
    bm25 = [(b, "slug-b", "t", "s", 0.5), (c, "slug-c", "t", "s", 0.4)]
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


def test_rrf_fuse_bm25_only_articles_included_as_synthetic_chunk() -> None:
    """Article ранжированная только BM25 (без vector chunk match) появляется
    в fused output как synthetic chunk_index=0 entry с FTS snippet'ом
    как text.

    Это симметричный fix к ранее асимметричному «BM25-only articles
    dropped» — улучшает recall особенно с imperfect / mock embeddings.
    Synthesis: slug + title из ArticleRepository.search row; text =
    ts_headline snippet (без HTML escaping — frontend sanitize'ит).
    """
    bm25_only = uuid4()
    fused = RetrievalService._rrf_fuse(
        vector_hits=[],
        bm25_articles=[(bm25_only, "slug-only", "title", "snippet text", 0.9)],
        top_k=10,
    )
    assert len(fused) == 1
    hit = fused[0]
    assert hit.article_id == bm25_only
    assert hit.slug == "slug-only"
    assert hit.title == "title"
    assert hit.chunk_index == 0
    assert hit.text == "snippet text"
    # Score = RRF от только BM25 rank=1: 1/(60+1) = 1/61.
    assert abs(hit.score - 1.0 / 61) < 1e-9

    # Mixed: vector chunk + другая BM25-only article — обе в output.
    other = uuid4()
    fused = RetrievalService._rrf_fuse(
        vector_hits=[_hit(other, chunk_index=0)],
        bm25_articles=[(bm25_only, "slug-only", "title", "snippet", 0.9)],
        top_k=10,
    )
    assert {h.article_id for h in fused} == {other, bm25_only}


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


# ---------------------------------------------------------------------------
# Reranker integration (#216)


@pytest.mark.asyncio
async def test_search_without_reranker_returns_rrf_order() -> None:
    """`reranker=None` → behavior backward-compatible."""
    a = uuid4()
    b = uuid4()
    svc, _, _ = _make_service(
        vector_hits=[_hit(a, chunk_index=0), _hit(b, chunk_index=0)],
        bm25_articles=[],
    )
    hits = await svc.search(query="хочу инфу", access_levels=frozenset([AccessLevel.PUBLIC]))
    assert len(hits) == 2
    # Vector order preserved (a первым).
    assert hits[0].article_id == a


@pytest.mark.asyncio
async def test_search_with_reranker_invokes_and_reorders() -> None:
    """Подключённый reranker применяется поверх RRF → topK."""
    from src.api.search.rerank import MockReranker

    a = uuid4()
    b = uuid4()
    # Two vector hits; query — содержит токены matchable only с hit b.
    embedding_repo = MagicMock()
    embedding_repo.search = AsyncMock(
        return_value=[
            RetrievalHit(
                article_id=a,
                slug="a",
                title="Article A",
                chunk_index=0,
                text="общая статья без ключевых слов",
                char_start=0,
                char_end=30,
                score=0.5,
            ),
            RetrievalHit(
                article_id=b,
                slug="b",
                title="Article B",
                chunk_index=0,
                text="залог сервисный платёж невозвратный",
                char_start=0,
                char_end=35,
                score=0.5,
            ),
        ]
    )
    article_repo = MagicMock()
    article_repo.search = AsyncMock(return_value=([], False))

    svc = RetrievalService(
        embedding_repo,
        article_repo,
        MockEmbeddingProvider(),
        reranker=MockReranker(),
        rerank_top_n=10,
    )
    # query matches text 'b' tokens.
    hits = await svc.search(
        query="сервисный залог",
        access_levels=frozenset([AccessLevel.PUBLIC]),
        top_k=2,
    )
    # Reranker должен промотить b на первое место.
    assert hits[0].article_id == b
    assert hits[1].article_id == a


@pytest.mark.asyncio
async def test_search_with_reranker_truncates_to_top_k() -> None:
    """rerank_top_n > top_k → reranker сортирует N, возвращаем K."""
    from src.api.search.rerank import MockReranker

    embedding_repo = MagicMock()
    embedding_repo.search = AsyncMock(
        return_value=[
            RetrievalHit(
                article_id=uuid4(),
                slug=f"a{i}",
                title=f"a{i}",
                chunk_index=0,
                text=f"text {i}",
                char_start=0,
                char_end=10,
                score=0.5,
            )
            for i in range(5)
        ]
    )
    article_repo = MagicMock()
    article_repo.search = AsyncMock(return_value=([], False))

    svc = RetrievalService(
        embedding_repo,
        article_repo,
        MockEmbeddingProvider(),
        reranker=MockReranker(),
        rerank_top_n=5,
    )
    hits = await svc.search(
        query="anything",
        access_levels=frozenset([AccessLevel.PUBLIC]),
        top_k=2,
    )
    assert len(hits) == 2


# ---------------------------------------------------------------------------
# _build_reranker factory


def test_build_reranker_disabled_returns_none() -> None:
    from src.api.search.retrieval import _build_reranker

    settings = Settings(RERANK_ENABLED=False)
    assert _build_reranker(settings) is None


def test_build_reranker_mock() -> None:
    from src.api.search.rerank import MockReranker
    from src.api.search.retrieval import _build_reranker

    settings = Settings(RERANK_ENABLED=True, RERANK_PROVIDER="mock")
    r = _build_reranker(settings)
    assert isinstance(r, MockReranker)


def test_build_reranker_unknown_raises() -> None:
    from src.api.search.retrieval import _build_reranker

    settings = Settings(RERANK_ENABLED=True, RERANK_PROVIDER="mock")
    object.__setattr__(settings, "rerank_provider", "bogus")
    with pytest.raises(ValueError, match="unknown rerank_provider"):
        _build_reranker(settings)
