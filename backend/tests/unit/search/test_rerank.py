"""Unit tests для cross-encoder reranker (#216, ADR-0010 follow-up).

MockReranker — детерминистический, testable без deps.
CrossEncoderReranker tests skipped без sentence-transformers — RAG smoke
job в CI installs deps + unskip'ает.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.api.search.repository import RetrievalHit
from src.api.search.rerank import MockReranker


def _hit(text: str, score: float = 0.5, slug: str = "art") -> RetrievalHit:
    return RetrievalHit(
        article_id=uuid4(),
        slug=slug,
        title="x",
        chunk_index=0,
        text=text,
        char_start=0,
        char_end=len(text),
        score=score,
    )


@pytest.mark.asyncio
async def test_mock_reranker_empty_input() -> None:
    r = MockReranker()
    assert await r.rerank("hello", []) == []


@pytest.mark.asyncio
async def test_mock_reranker_reorders_by_token_overlap() -> None:
    r = MockReranker()
    hits = [
        _hit("article about cats and dogs", slug="a"),  # 1 token match с query (cats)
        _hit("kittens and felines and cats", slug="b"),  # 1 match (cats) — но всё равно score
        _hit("nothing relevant here", slug="c"),  # 0 matches
    ]
    out = await r.rerank("cats food", hits)
    # All hits returned; reordered by score desc.
    assert len(out) == 3
    # 'nothing relevant' should be last.
    assert out[-1].text == "nothing relevant here"
    # Scores updated (not 0.5 default).
    assert out[0].score >= out[1].score >= out[2].score


@pytest.mark.asyncio
async def test_mock_reranker_empty_query_preserves_order() -> None:
    """Пустой query → нечего matchить, оставляем оригинальный порядок."""
    r = MockReranker()
    hits = [_hit("a", slug="1"), _hit("b", slug="2")]
    out = await r.rerank("", hits)
    assert [h.slug for h in out] == ["1", "2"]


@pytest.mark.asyncio
async def test_mock_reranker_ignores_short_tokens() -> None:
    """≤2-char tokens skipped (filter shorten noise). 'is/at' не считаются."""
    r = MockReranker()
    hits = [_hit("is at on", slug="short")]
    # query = "is at" → tokens >=3 char: пусто → all scores fall back
    # на preserve order.
    out = await r.rerank("is at", hits)
    assert len(out) == 1


def test_mock_reranker_has_model_id() -> None:
    """`model_id` exposed для logging."""
    assert MockReranker().model_id == "mock-rerank-v1"
    assert MockReranker("custom-id").model_id == "custom-id"


@pytest.mark.asyncio
async def test_mock_reranker_score_replaced_not_dropped() -> None:
    """RetrievalHit.score обновлён на cross-encoder-style score."""
    r = MockReranker()
    hits = [_hit("hello world test", score=0.99)]  # original RRF score
    [out] = await r.rerank("hello", hits)
    # Score replaced (не оригинальный 0.99).
    assert out.score != 0.99
    # Остальные fields preserved.
    assert out.text == "hello world test"


# ---------------------------------------------------------------------------
# Provider label dispatch (regression test, PR #262 reviewer concern §2)


def test_rerank_provider_label_mock() -> None:
    """MockReranker → 'mock' label."""
    from src.api.search.retrieval import _rerank_provider_label

    assert _rerank_provider_label(MockReranker()) == "mock"


def test_rerank_provider_label_unknown() -> None:
    """Custom Reranker, не один из known классов → 'unknown' (catches
    misconfiguration in dashboard rather than silently labeling as
    cross_encoder)."""
    from src.api.search.retrieval import _rerank_provider_label

    class _CustomReranker:
        @property
        def model_id(self) -> str:
            return "custom"

        async def rerank(self, query: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
            return hits

    assert _rerank_provider_label(_CustomReranker()) == "unknown"
