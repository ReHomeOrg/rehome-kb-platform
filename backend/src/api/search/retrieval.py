"""RetrievalService — hybrid BM25 + vector + RRF fusion (#132).

End-to-end query flow (ADR-0010 §"Stage 1 — Retrieval"):
1. Embed query через provider (одна call → одна vector).
2. Vector top-30: `EmbeddingRepository.search` (cosine distance, JOIN
   articles на access_level + status).
3. BM25 top-30: existing `ArticleRepository.search` (Postgres FTS,
   landed в E2.5a #46). Same access_level + status filter.
4. Symmetric RRF fusion (k=60):
       score = 1/(k + v_rank+1) + 1/(k + b_rank+1)
   - Vector chunks сохраняют chunk_index + text fragment.
   - BM25-only articles (нет в vector top-K) добавляются как synthetic
     chunk_index=0 entries с FTS snippet'ом как text — обеспечивает
     recall для articles которые FTS matches strongly но vector miss'ил
     (особенно critical при mock embeddings или imperfect production
     model). До 2026-05-28 был asymmetric drop — fixed.
5. Sort by fused score desc → top_k chunks (chunk-granularity output;
   downstream `_dedupe_by_article` опционально dedup'нет для citations).

Result type: `RetrievalHit` (re-used от repository).
"""

import logging
import re
import time
from collections.abc import Sequence
from typing import Final
from uuid import UUID

from fastapi import Depends

from src.api.articles.repository import ArticleRepository, get_article_repository
from src.api.auth.scope import AccessLevel
from src.api.config import Settings, get_settings
from src.api.search.embeddings import EmbeddingProvider, MockEmbeddingProvider
from src.api.search.metrics import (
    RERANK_DURATION_SECONDS,
    RERANK_HITS,
    RERANK_TOTAL,
    RETRIEVAL_DURATION_SECONDS,
    RETRIEVAL_HITS,
    RETRIEVAL_TOTAL,
)
from src.api.search.repository import (
    EmbeddingRepository,
    QAEmbeddingRepository,
    RetrievalHit,
    get_embedding_repository,
    get_qa_embedding_repository,
)
from src.api.search.rerank import MockReranker, Reranker

# Postgres `ts_headline` обёртывает FTS matches в `<b>...</b>`. Для chat
# LLM context это noise. Frontend (DOMPurify) sanitizes для own render —
# RetrievalHit.text идёт И туда И в LLM, поэтому очищаем здесь.
_BM25_MARKUP_RE: Final = re.compile(r"</?b>", re.IGNORECASE)


def _strip_bm25_markup(snippet: str) -> str:
    """Drop `<b>` / `</b>` markup из ts_headline output."""
    return _BM25_MARKUP_RE.sub("", snippet)


def _rerank_provider_label(reranker: Reranker) -> str:
    """Map reranker instance → Prometheus label (fixed cardinality).

    Explicit isinstance checks per known class — defensive against
    future Reranker implementations (e.g., remote API rerank) being
    silently mislabeled as 'cross_encoder'. New types: add explicit branch.
    Unknown → 'unknown' (catches the misconfiguration in dashboards).
    """
    if isinstance(reranker, MockReranker):
        return "mock"
    # Lazy import — CrossEncoderReranker импортирует sentence_transformers
    # которая не установлена в default API контейнере. isinstance работает
    # даже без installed deps т.к. класс импортирует на module level в
    # rerank.py.
    from src.api.search.rerank import CrossEncoderReranker

    if isinstance(reranker, CrossEncoderReranker):
        return "cross_encoder"
    return "unknown"


# Row shape от `ArticleRepository.search`: (id, title, snippet, ts_rank).
# Используется только для индекса rank (id) — поля title/snippet/score
# игнорируются в fusion. Алиас облегчает refactoring если ArticleRepository
# когда-нибудь поменяет shape.
type BM25Row = tuple[UUID, str, str, str | None, float]
# (id, slug, title, snippet, ts_rank) — per ArticleRepository.search.

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
        reranker: Reranker | None = None,
        rerank_top_n: int = 20,
        qa_repo: QAEmbeddingRepository | None = None,
    ) -> None:
        self._embedding_repo = embedding_repo
        self._article_repo = article_repo
        self._provider = provider
        # `reranker=None` → re-ranking off, чистый RRF flow (default).
        # Когда подключён, RRF возвращает top_n → reranker → top_k.
        self._reranker = reranker
        self._rerank_top_n = rerank_top_n
        # `qa_repo=None` → Q&A corpus skipped (backward-compat default;
        # callers до 2026-05-29 не передают). Production wiring через
        # `get_retrieval_service` подаёт настоящий QAEmbeddingRepository.
        self._qa_repo = qa_repo

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
            RETRIEVAL_TOTAL.labels(has_results="no").inc()
            RETRIEVAL_HITS.observe(0)
            return []

        started = time.perf_counter()
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

        # 2b. Q&A corpus — third parallel retriever (2026-05-29, ТЗ
        # Чат-поиск §«корпуса»). ANSWERED article_questions indexed
        # отдельной таблицей; vector-only retrieval (BM25 для Q&A — на
        # будущее). Гарантирует что user-answered questions попадают в
        # RAG context следующего запроса.
        qa_hits: list[RetrievalHit] = []
        if self._qa_repo is not None:
            qa_hits = await self._qa_repo.search(
                query_vector=query_vector,
                access_levels=access_levels,
                model_id=self._provider.model_id,
                top_k=per_retriever_k,
            )

        # 4. RRF fusion. Если reranker подключён — fuse'им до большего
        # top_n (даёт reranker'у пространство для promote'а далёких RRF
        # hits), затем cross-encoder reorders top_n → output top_k.
        fuse_k = max(top_k, self._rerank_top_n) if self._reranker else top_k
        result = self._rrf_fuse(vector_hits, bm25_hits, qa_hits, top_k=fuse_k)

        if self._reranker is not None and result:
            rerank_label = _rerank_provider_label(self._reranker)
            RERANK_HITS.observe(len(result))
            rerank_started = time.perf_counter()
            result = await self._reranker.rerank(query, result)
            RERANK_DURATION_SECONDS.labels(provider=rerank_label).observe(
                time.perf_counter() - rerank_started
            )
            RERANK_TOTAL.labels(provider=rerank_label).inc()
            result = result[:top_k]

        RETRIEVAL_DURATION_SECONDS.observe(time.perf_counter() - started)
        RETRIEVAL_HITS.observe(len(result))
        RETRIEVAL_TOTAL.labels(has_results="yes" if result else "no").inc()
        return result

    @staticmethod
    def _rrf_fuse(
        vector_hits: list[RetrievalHit],
        # `Sequence` (covariant) чтобы принять `list[tuple[UUID, str,
        # str, float]]` от ArticleRepository.search — list invariant.
        bm25_articles: Sequence[BM25Row],
        qa_hits: list[RetrievalHit],
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        """Symmetric RRF: chunk-level granularity + BM25-only synthesis
        + Q&A vector hits как третий retriever.

        Vector retriever отдаёт chunk-level granularity (chunk_index + text
        fragment). BM25 — article-level (id + slug + title + snippet).
        Q&A retriever (`qa_hits`) — per-question vector hits, source_type
        уже set в "article_question" со своим question_id.

        Fusion:
        1. Каждый vector chunk сохраняется со score = 1/(_RRF_K + v_rank+1).
        2. Если article также matches BM25 — все её chunks получают boost
           1/(_RRF_K + b_rank+1).
        3. BM25-only articles (не в vector top-K) добавляются как
           synthetic chunk_index=0 entries — slug+title+snippet как text.
           Это симметрично vector-only path и обеспечивает recall для
           articles которые FTS matches strongly но vector miss'ил
           (особенно critical при mock embeddings).
        4. Q&A hits добавляются с rank-based score: каждый Q&A hit
           independent от article fusion (даже если parent article в
           bm25_articles, Q&A — отдельная единица знания). Deduplicate'ятся
           по `question_id` (на случай дублирования в input).
        5. Output — chunk-granularity (downstream consumers dedup'ают
           по article_id если им нужно — например `/search` endpoint
           через `_dedupe_by_article`).
        """
        bm25_rank_by_article = {
            article_row[0]: rank for rank, article_row in enumerate(bm25_articles)
        }
        bm25_meta_by_article: dict[UUID, BM25Row] = {row[0]: row for row in bm25_articles}

        fused: list[tuple[float, RetrievalHit]] = []
        vector_article_ids: set[UUID] = set()

        # Vector chunks (chunk-granularity preserved).
        for v_rank, hit in enumerate(vector_hits):
            score = 1.0 / (_RRF_K + v_rank + 1)
            b_rank = bm25_rank_by_article.get(hit.article_id)
            if b_rank is not None:
                score += 1.0 / (_RRF_K + b_rank + 1)
            vector_article_ids.add(hit.article_id)
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

        # BM25-only — synthesize chunk_index=0 entry с FTS snippet'ом.
        # Только для articles которые ОТСУТСТВУЮТ в vector hits полностью
        # (иначе уже представлены своими реальными chunks).
        for article_id, (_, slug, title, snippet, _ts_rank) in bm25_meta_by_article.items():
            if article_id in vector_article_ids:
                continue
            b_rank = bm25_rank_by_article[article_id]
            score = 1.0 / (_RRF_K + b_rank + 1)
            # `ts_headline` обёртывает matches в `<b>...</b>` (FTS markup).
            # Frontend sanitizes (DOMPurify whitelist `<b>`); но в chat LLM
            # context эти tags — noise (модель может процитировать as-is
            # или путаться). Strip перед сохранением в RetrievalHit.text.
            clean_snippet = _strip_bm25_markup(snippet or "")
            fused.append(
                (
                    score,
                    RetrievalHit(
                        article_id=article_id,
                        slug=slug,
                        title=title,
                        chunk_index=0,
                        text=clean_snippet,
                        char_start=0,
                        char_end=len(clean_snippet),
                        score=score,
                    ),
                )
            )

        # Q&A vector hits. Каждый Q&A — independent unit of knowledge
        # (НЕ часть parent article body); score основан на собственном
        # rank в qa_hits list (не fused с article ranks). Dedup по
        # question_id защищает от duplicate input.
        seen_question_ids: set[UUID] = set()
        for q_rank, hit in enumerate(qa_hits):
            if hit.question_id is None or hit.question_id in seen_question_ids:
                continue
            seen_question_ids.add(hit.question_id)
            score = 1.0 / (_RRF_K + q_rank + 1)
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
                        source_type="article_question",
                        question_id=hit.question_id,
                    ),
                )
            )

        fused.sort(key=lambda x: -x[0])
        return [hit for _, hit in fused[:top_k]]


def _build_provider(settings: Settings) -> EmbeddingProvider:
    """Provider factory по `settings.embedding_provider`.

    - `"mock"` — deterministic SHA-based, для dev / tests (см.
      `embeddings.py`).
    - `"hf"` — sentence-transformers (см. `embeddings_hf.py`). Импорт
      ленивый: PyTorch + transformers — ~2 GB деп, не загружаются в
      main API контейнер. Используется в dedicated indexer worker;
      главный gateway работает с `mock` пока прод-cutover не сделан.
    """
    choice = settings.embedding_provider.lower()
    if choice == "mock":
        # Mock использует свой стабильный `mock-v1` model_id (не
        # `settings.embedding_model`) — fake vectors не должны share
        # model_id с реальной production model, иначе blue-green
        # invariant сломается при последующем switch на 'hf'.
        return MockEmbeddingProvider()
    if choice == "hf":
        # Lazy import — `embeddings_hf` импортирует sentence_transformers
        # которая не установлена в default API контейнере.
        from src.api.search.embeddings_hf import (
            SentenceTransformersEmbeddingProvider,
        )

        return SentenceTransformersEmbeddingProvider(
            model_name=settings.embedding_model,
            dim=settings.embedding_dim,
        )
    raise ValueError(
        f"unknown embedding_provider={settings.embedding_provider!r}; expected 'mock' or 'hf'"
    )


def _build_reranker(settings: Settings) -> Reranker | None:
    """`RERANK_ENABLED=false` (default) → None — re-ranking off.

    При `true` returns MockReranker либо CrossEncoderReranker (lazy
    sentence_transformers import).
    """
    if not settings.rerank_enabled:
        return None
    choice = settings.rerank_provider.lower()
    if choice == "mock":
        return MockReranker()
    if choice == "cross_encoder":
        from src.api.search.rerank import CrossEncoderReranker

        return CrossEncoderReranker(model_name=settings.rerank_model)
    raise ValueError(
        f"unknown rerank_provider={settings.rerank_provider!r}; expected 'mock' or 'cross_encoder'"
    )


def get_retrieval_service(
    embedding_repo: EmbeddingRepository = Depends(get_embedding_repository),
    article_repo: ArticleRepository = Depends(get_article_repository),
    settings: Settings = Depends(get_settings),
    qa_repo: QAEmbeddingRepository = Depends(get_qa_embedding_repository),
) -> RetrievalService:
    """FastAPI dependency — RetrievalService с settings-driven provider.

    Default `EMBEDDING_PROVIDER=mock` для dev / tests. Production
    переключение на `hf` — после landing'а HF embedder + ingest'а
    real vectors через indexer worker.

    `RERANK_ENABLED=true` подключает cross-encoder поверх RRF top-N.

    `qa_repo` подаётся всегда (одна и та же AsyncSession dep) — Q&A
    corpus extension включена unconditionally; пустой corpus = empty hits.
    """
    return RetrievalService(
        embedding_repo,
        article_repo,
        _build_provider(settings),
        reranker=_build_reranker(settings),
        rerank_top_n=settings.rerank_top_n,
        qa_repo=qa_repo,
    )
