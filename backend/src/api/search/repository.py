"""EmbeddingRepository — write side (kb-search Stage 1, #128).

Write operations для `article_embeddings` table:
- `upsert(article_id, chunks, embeddings, model_id)` — atomic write
  whole article's embeddings. INSERT ... ON CONFLICT (article_id,
  chunk_index, embedding_model_id) DO UPDATE — supports replay (article
  re-indexed → same chunks вытесняют old).
- `delete_by_article(article_id)` — cleanup на article archive/delete.
  Article CASCADE FK auto-handles это в DB; method для explicit cleanup
  без удаления article (rare; soft-delete pattern).
- `delete_by_model(model_id)` — cleanup старой model после blue-green
  switch (ADR-0010 §"Re-embedding на model bump").

Read side (`search()` / `query()`) — отдельный PR с retrieval logic.

### ADR-0003 invariant — split responsibility

Write-side НЕ enforce'ит `access_level` фильтр: chunks inherit от parent
article через CASCADE FK (`models.py:31-34`). Если article создаётся /
обновляется — текущий access_level применяется до chunks transitively на
retrieval-стороне.

Retrieval PR (отдельный) обязан JOIN'ить с `articles` по
`access_level IN (...)` в каждой query — это unavoidable storage-level
гарантия. См. ADR-0003 + `articles/repository.py` как reference pattern.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.models import Article, ArticleQuestion
from src.api.auth.scope import AccessLevel
from src.api.db import get_session
from src.api.search.chunker import Chunk
from src.api.search.models import ArticleEmbedding, ArticleQuestionEmbedding


@dataclass(frozen=True)
class RetrievalHit:
    """Single retrieved chunk с denormalized article fields для citations.

    `source_type` различает article body vs answered Q&A; frontend
    рендерит разные variant'ы карточек (см. ТЗ Чат-поиск §«корпуса»).
    `question_id` set'нут только для Q&A hits — используется для
    deep-link'а `/articles/{slug}#question-{id}`.
    """

    article_id: UUID
    slug: str
    title: str
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    # Score depends на источник: cosine distance для vector search
    # (lower = closer), RRF fused score для hybrid (higher = better). Caller
    # знает context.
    score: float
    # Source type — backwards-compatible default; existing call sites не
    # затрагиваются.
    source_type: str = "article"
    # Set только для source_type="article_question". Для article = None.
    question_id: UUID | None = None


class EmbeddingRepository:
    """Storage layer для article_embeddings."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        article_id: UUID,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        model_id: str,
    ) -> int:
        """INSERT всех chunks одной article atomic.

        ON CONFLICT (article_id, chunk_index, embedding_model_id) DO UPDATE —
        replay-safe (re-index того же article через же model просто
        overwrite'ит rows). Возвращает count rows affected.

        Caller отвечает за commit (consistent с другими репозиториями).
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) and embeddings ({len(embeddings)}) length mismatch"
            )
        if not chunks:
            return 0

        values: list[dict[str, Any]] = []
        for idx, (chunk, emb) in enumerate(zip(chunks, embeddings, strict=True)):
            values.append(
                {
                    "article_id": article_id,
                    "chunk_index": idx,
                    "embedding_model_id": model_id,
                    "embedding": emb,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                }
            )

        stmt = pg_insert(ArticleEmbedding).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["article_id", "chunk_index", "embedding_model_id"],
            set_={
                "embedding": stmt.excluded.embedding,
                "char_start": stmt.excluded.char_start,
                "char_end": stmt.excluded.char_end,
            },
        )
        await self._session.execute(stmt)
        await self._session.flush()
        return len(values)

    async def delete_by_article(self, article_id: UUID) -> int:
        """Удалить все embeddings одной статьи (любой model_id).

        Caller отвечает за commit (consistent с другими репозиториями).
        """
        stmt = delete(ArticleEmbedding).where(ArticleEmbedding.article_id == article_id)
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)

    async def search(
        self,
        *,
        query_vector: list[float],
        access_levels: frozenset[AccessLevel],
        model_id: str,
        top_k: int = 30,
    ) -> list[RetrievalHit]:
        """Vector retrieval по cosine distance с ADR-0003 access filter.

        Cosine distance — `embedding <=> query` (pgvector operator, lower
        = closer). Uses HNSW index `ix_article_embeddings_hnsw` (created
        в migration 0014).

        JOIN с articles обязателен для:
        - `status='PUBLISHED'` (соответствует chat read-mask).
        - `access_level IN (caller's scope)` — storage-level enforcement
          ADR-0003. Без JOIN'а кто-то мог бы retrieve chunks от чужого
          access tier.
        - Chunk text — reconstruct'ится via `SUBSTRING(body_markdown FROM
          char_start+1 FOR length)`. Postgres 1-indexed, `char_start`
          0-indexed (Python convention) → +1.
        - `slug` для citations.

        `model_id` фильтр — retrieval только для current production model
        (blue-green: новый model_id ingest'ится параллельно, search
        переключится после coverage 100%).

        Returns top_k results, ordered by ascending distance.
        """
        allowed = [level.value for level in access_levels]
        if not allowed:
            return []

        # Postgres SUBSTRING(string FROM start FOR length); offsets 1-indexed.
        # `+1` конвертирует Python 0-indexed char_start → SQL.
        text_expr = func.substring(
            Article.body_markdown,
            ArticleEmbedding.char_start + 1,
            ArticleEmbedding.char_end - ArticleEmbedding.char_start,
        ).label("text")
        # `embedding <=> :query` — pgvector cosine distance.
        # `cosine_distance` method (vs raw op("<=>")) — типизирует return как
        # Float, иначе SQLAlchemy наследует Vector type → падает на read
        # `Vector._from_db('float')`. См. pgvector/sqlalchemy/vector.py.
        distance_expr = ArticleEmbedding.embedding.cosine_distance(query_vector).label("distance")

        stmt = (
            select(
                ArticleEmbedding.article_id,
                Article.slug,
                Article.title,
                ArticleEmbedding.chunk_index,
                text_expr,
                ArticleEmbedding.char_start,
                ArticleEmbedding.char_end,
                distance_expr,
            )
            .join(Article, Article.id == ArticleEmbedding.article_id)
            .where(
                Article.status == "PUBLISHED",
                Article.access_level.in_(allowed),
                ArticleEmbedding.embedding_model_id == model_id,
            )
            .order_by(distance_expr.asc())
            .limit(top_k)
        )
        result = await self._session.execute(stmt)
        return [
            RetrievalHit(
                article_id=row.article_id,
                slug=row.slug,
                title=row.title,
                chunk_index=row.chunk_index,
                text=row.text,
                char_start=row.char_start,
                char_end=row.char_end,
                score=float(row.distance),
            )
            for row in result
        ]

    async def delete_by_article_slug(self, slug: str) -> int:
        """Same as `delete_by_article` но resolve'ит article_id по slug.

        Используется когда вызывающий код имеет только slug (e.g.,
        `DELETE /articles/{slug}` archive handler — он soft-delete'ит
        article и не имеет id напрямую). Single round-trip subquery —
        не extra DB call.

        ADR-0003: subquery НЕ применяет `access_level` filter — это
        downstream от `articles.repository.archive()` где writer-side
        auth уже выполнен (writer не вызовет archive если не имеет access
        к статье). Этот delete — clean-up уже-authorized операции.

        Caller отвечает за commit.
        """
        subquery = select(Article.id).where(Article.slug == slug)
        stmt = delete(ArticleEmbedding).where(ArticleEmbedding.article_id.in_(subquery))
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)

    async def delete_by_model(self, model_id: str) -> int:
        """Удалить все embeddings под конкретной model_id.

        Используется после blue-green switch: после того как new model
        достигла 100% coverage и production retrieval переключился, можно
        cleanup'ить старые vectors (free disk space).

        Caller отвечает за commit (consistent с другими репозиториями).
        """
        stmt = delete(ArticleEmbedding).where(ArticleEmbedding.embedding_model_id == model_id)
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)


def get_embedding_repository(
    session: AsyncSession = Depends(get_session),
) -> EmbeddingRepository:
    return EmbeddingRepository(session)


# ---------------------------------------------------------------------------
# Q&A embedding repository (2026-05-29)


class QAEmbeddingRepository:
    """Storage layer для article_question_embeddings (Q&A RAG corpus).

    Mirror'ит EmbeddingRepository API но per-question, single chunk
    (Q+A textы короткие). text материализован в row (`text_indexed`) —
    PII-masked перед persist'ом, retrieval отдаёт его прямо в LLM
    context.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        question_id: UUID,
        embedding: list[float],
        text_indexed: str,
        model_id: str,
    ) -> None:
        """INSERT … ON CONFLICT DO UPDATE — replay-safe (re-index same
        question под тем же model_id overwrites).

        Caller отвечает за commit.
        """
        stmt = pg_insert(ArticleQuestionEmbedding).values(
            article_question_id=question_id,
            embedding_model_id=model_id,
            embedding=embedding,
            text_indexed=text_indexed,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["article_question_id", "embedding_model_id"],
            set_={
                "embedding": stmt.excluded.embedding,
                "text_indexed": stmt.excluded.text_indexed,
            },
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def delete_by_question(self, question_id: UUID) -> int:
        """Удалить все embeddings одного question'а (любой model_id).

        Вызывается на DISMISSED / revert PENDING — терминал-state «нет
        публичного ответа», embedding должен быть evict'нут чтобы chat
        не вернул stale ответ.

        Caller отвечает за commit.
        """
        stmt = delete(ArticleQuestionEmbedding).where(
            ArticleQuestionEmbedding.article_question_id == question_id
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)

    async def delete_by_model(self, model_id: str) -> int:
        """Cleanup всех Q&A vectors под конкретной model — для blue-green
        switch post-cutover (mirror EmbeddingRepository.delete_by_model)."""
        stmt = delete(ArticleQuestionEmbedding).where(
            ArticleQuestionEmbedding.embedding_model_id == model_id
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return int(result.rowcount or 0)

    async def search(
        self,
        *,
        query_vector: list[float],
        access_levels: frozenset[AccessLevel],
        model_id: str,
        top_k: int = 30,
    ) -> list[RetrievalHit]:
        """Vector retrieval по cosine distance с ADR-0003 access filter.

        JOIN chain `article_question_embeddings → article_questions →
        articles` обязателен для:
        - `articles.status='PUBLISHED'` (mirror article retrieval).
        - `articles.access_level IN (caller scope)` — ADR-0003 enforced
          через JOIN parent article.
        - `article_questions.status='ANSWERED'` — defence-in-depth.
          Indexer уже не должен embeddings'ить PENDING/DISMISSED, но
          мало ли race / data corruption.
        - `articles.slug` / `articles.title` для citation rendering.

        Returns chunks с `source_type="article_question"` + `question_id`
        для frontend deep-link'а `/articles/{slug}#question-{id}`.
        """
        allowed = [level.value for level in access_levels]
        if not allowed:
            return []

        distance_expr = ArticleQuestionEmbedding.embedding.cosine_distance(query_vector).label(
            "distance"
        )

        stmt = (
            select(
                ArticleQuestion.id.label("question_id"),
                ArticleQuestion.article_id,
                Article.slug,
                Article.title,
                ArticleQuestionEmbedding.text_indexed,
                distance_expr,
            )
            .join(
                ArticleQuestion,
                ArticleQuestion.id == ArticleQuestionEmbedding.article_question_id,
            )
            .join(Article, Article.id == ArticleQuestion.article_id)
            .where(
                Article.status == "PUBLISHED",
                Article.access_level.in_(allowed),
                ArticleQuestion.status == "ANSWERED",
                ArticleQuestionEmbedding.embedding_model_id == model_id,
            )
            .order_by(distance_expr.asc())
            .limit(top_k)
        )
        result = await self._session.execute(stmt)
        return [
            RetrievalHit(
                article_id=row.article_id,
                slug=row.slug,
                title=row.title,
                # chunk_index=0 — single chunk per question; ADR-0010
                # tuple (article_id, chunk_index) уникальность не страдает
                # т.к. dedup'ы делаются по (article_id, source_type, question_id).
                chunk_index=0,
                text=row.text_indexed,
                char_start=0,
                char_end=len(row.text_indexed),
                score=float(row.distance),
                source_type="article_question",
                question_id=row.question_id,
            )
            for row in result
        ]


def get_qa_embedding_repository(
    session: AsyncSession = Depends(get_session),
) -> QAEmbeddingRepository:
    return QAEmbeddingRepository(session)
