"""RetrievalService — hybrid BM25 + vector + RRF fusion (#132).

End-to-end query flow (ADR-0010 §"Stage 1 — Retrieval"):
1. Embed query через provider (одна call → одна vector).
2. Vector top-30: `EmbeddingRepository.search` (cosine distance, JOIN
   articles на access_level + status).
3. BM25 top-30: existing `ArticleRepository.search` (Postgres FTS,
   landed в E2.5a #46). Same access_level + status filter.
4. RRF fusion (k=60):
       score = 1/(k + v_rank+1) + 1/(k + b_rank+1)
   Asymmetric — vector-only hits OK (если no BM25 match, contributing
   только vector term). BM25-only article hits → 0 (т.к. нет chunk
   granularity без vector hit).
5. Sort by fused score desc → top_k chunks.

Result type: `RetrievalHit` (re-used от repository).
"""

import logging
from typing import Any, Final

from fastapi import Depends

from src.api.articles.repository import ArticleRepository, get_article_repository
from src.api.auth.scope import AccessLevel
from src.api.search.embeddings import EmbeddingProvider, MockEmbeddingProvider
from src.api.search.repository import (
    EmbeddingRepository,
    RetrievalHit,
    get_embedding_repository,
)

logger = logging.getLogger(__name__)

# RRF constant per standard literature
# (Cormack/Clarke/Buettcher, SIGIR 2009 — see ADR-0010 References).
_RRF_K: Final = 60

# Default retrieval breadth: pull top-30 from each retriever, return top-10
# after fusion. ADR-0010 §"Stage 1" tuning.
DEFAULT_PER_RETRIEVER_K: Final = 30
DEFAULT_FUSED_TOP_K: Final = 10


class RetrievalService:
    """Hybrid retrieval orchestrator."""

    def __init__(
        self,
        embedding_repo: EmbeddingRepository,
        article_repo: ArticleRepository,
        provider: EmbeddingProvider,
    ) -> None:
        self._embedding_repo = embedding_repo
        self._article_repo = article_repo
        self._provider = provider

    async def search(
        self,
        *,
        query: str,
        access_levels: frozenset[AccessLevel],
        top_k: int = DEFAULT_FUSED_TOP_K,
        per_retriever_k: int = DEFAULT_PER_RETRIEVER_K,
    ) -> list[RetrievalHit]:
        """Hybrid search query → top_k chunks fused from vector + BM25.

        Empty query / no access levels → empty list (defensive).
        """
        if not query.strip() or not access_levels:
            return []

        # 1. Embed query.
        embeddings = await self._provider.embed([query])
        query_vector = embeddings[0]

        # 2-3. Parallel retrievers — vector + BM25.
        # Sequential для simplicity; `asyncio.gather` дал бы небольшой win,
        # но обе queries hit same DB pool — overlap нетривиален.
        vector_hits = await self._embedding_repo.search(
            query_vector=query_vector,
            access_levels=access_levels,
            model_id=self._provider.model_id,
            top_k=per_retriever_k,
        )
        bm25_hits, _has_more = await self._article_repo.search(
            query,
            access_levels,
            cursor=None,
            limit=per_retriever_k,
        )

        # 4. RRF fusion.
        return self._rrf_fuse(vector_hits, bm25_hits, top_k=top_k)

    @staticmethod
    def _rrf_fuse(
        vector_hits: list[RetrievalHit],
        # BM25 rows shape from ArticleRepository.search: (id, title,
        # snippet, score). Hetero-typed — Any для caller-typed clarity.
        bm25_articles: list[tuple[Any, ...]],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        """Asymmetric RRF: chunks from vector + article BM25 ranks.

        BM25 returns articles (no chunk granularity) — promote'им
        BM25 rank на все chunks этой статьи (via lookup map).
        """
        bm25_rank_by_article = {
            article_row[0]: rank + 1 for rank, article_row in enumerate(bm25_articles)
        }
        fused: list[tuple[float, RetrievalHit]] = []
        for v_rank, hit in enumerate(vector_hits):
            score = 1.0 / (_RRF_K + v_rank + 1)
            b_rank = bm25_rank_by_article.get(hit.article_id)
            if b_rank is not None:
                score += 1.0 / (_RRF_K + b_rank)
            # Replace cosine distance в `score` field на fused RRF score
            # (chat / endpoint consumers ожидают "higher = better").
            fused.append(
                (
                    score,
                    RetrievalHit(
                        article_id=hit.article_id,
                        slug=hit.slug,
                        chunk_index=hit.chunk_index,
                        text=hit.text,
                        char_start=hit.char_start,
                        char_end=hit.char_end,
                        score=score,
                    ),
                )
            )
        fused.sort(key=lambda x: -x[0])
        return [hit for _, hit in fused[:top_k]]


def get_retrieval_service(
    embedding_repo: EmbeddingRepository = Depends(get_embedding_repository),
    article_repo: ArticleRepository = Depends(get_article_repository),
) -> RetrievalService:
    """FastAPI dependency — RetrievalService с default MockProvider.

    Real provider deploy'ится separate worker (ADR-0010). Gateway query
    side всё ещё использует Mock (deterministic for tests). Когда real
    indexer landed prod-side, ingest'ит real vectors, и gateway query
    embedder перейдёт на ту же real model — отдельная wire-up.
    """
    return RetrievalService(embedding_repo, article_repo, MockEmbeddingProvider())
