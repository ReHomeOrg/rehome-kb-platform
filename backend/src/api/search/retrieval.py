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
   только vector term). **BM25-only article hits dropped**: т.к. fusion
   итерирует по `vector_hits` (chunk granularity), статья ранжированная
   только BM25 без vector chunk match в output не попадёт. Это
   осознанный trade-off: chunk granularity у output обязательна для
   citations / chat-grounding (article без конкретного chunk
   бесполезна), а vector с правильно настроенным top-K (30) на типичных
   ru-IR workloads даёт высокую recall. Регрессионный тест:
   `test_rrf_fuse_bm25_only_articles_dropped`.
5. Sort by fused score desc → top_k chunks.

Result type: `RetrievalHit` (re-used от repository).
"""

import logging
from collections.abc import Sequence
from typing import Final
from uuid import UUID

from fastapi import Depends

from src.api.articles.repository import ArticleRepository, get_article_repository
from src.api.auth.scope import AccessLevel
from src.api.config import Settings, get_settings
from src.api.search.embeddings import EmbeddingProvider, MockEmbeddingProvider
from src.api.search.repository import (
    EmbeddingRepository,
    RetrievalHit,
    get_embedding_repository,
)

# Row shape от `ArticleRepository.search`: (id, title, snippet, ts_rank).
# Используется только для индекса rank (id) — поля title/snippet/score
# игнорируются в fusion. Алиас облегчает refactoring если ArticleRepository
# когда-нибудь поменяет shape.
type BM25Row = tuple[UUID, str, str | None, float]

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

        # 2-3. Vector + BM25 retrievers, sequential.
        # `asyncio.gather` НЕ применим: обе queries исполняются на одной
        # `AsyncSession`, а SQLAlchemy AsyncSession не concurrency-safe
        # (одна connection одновременно — один statement). Параллельность
        # потребовала бы second `AsyncSession` per retriever — сложность
        # на уровне DI ради ~50ms win'а. Punt'ит до того как retrieval
        # станет hot path.
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
        # `Sequence` (covariant) чтобы принять `list[tuple[UUID, str,
        # str, float]]` от ArticleRepository.search — list invariant.
        bm25_articles: Sequence[BM25Row],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        """Asymmetric RRF: chunks from vector + article BM25 ranks.

        BM25 returns articles (no chunk granularity) — promote'им
        BM25 rank на все chunks этой статьи (via lookup map). Статьи,
        ранжированные только BM25 без vector match, в output не
        попадают: см. docstring модуля §"BM25-only article hits dropped".
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
                        title=hit.title,
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


def _build_provider(settings: Settings) -> EmbeddingProvider:
    """Provider factory по `settings.embedding_provider`.

    - `"mock"` — deterministic SHA-based, для dev / tests (см.
      `embeddings.py`).
    - `"hf"` — sentence-transformers, real `intfloat/multilingual-e5-large`.
      Импорт ленивый: PyTorch / transformers — ~2 GB деп, не нужны в
      Mock-режиме. Сам HF-provider landing'ится в follow-up; пока в
      `"hf"` режиме fail-fast с ясным сообщением.
    """
    choice = settings.embedding_provider.lower()
    if choice == "mock":
        # Mock использует свой стабильный `mock-v1` model_id (не
        # `settings.embedding_model`) — fake vectors не должны share
        # model_id с реальной production model, иначе blue-green
        # invariant сломается при последующем switch на 'hf'.
        return MockEmbeddingProvider()
    if choice == "hf":
        raise RuntimeError(
            "embedding_provider='hf' selected but HF provider not yet "
            "implemented; set EMBEDDING_PROVIDER=mock or wait for follow-up PR"
        )
    raise ValueError(
        f"unknown embedding_provider={settings.embedding_provider!r}; " "expected 'mock' or 'hf'"
    )


def get_retrieval_service(
    embedding_repo: EmbeddingRepository = Depends(get_embedding_repository),
    article_repo: ArticleRepository = Depends(get_article_repository),
    settings: Settings = Depends(get_settings),
) -> RetrievalService:
    """FastAPI dependency — RetrievalService с settings-driven provider.

    Default `EMBEDDING_PROVIDER=mock` для dev / tests. Production
    переключение на `hf` — после landing'а HF embedder + ingest'а
    real vectors через indexer worker.
    """
    return RetrievalService(embedding_repo, article_repo, _build_provider(settings))
