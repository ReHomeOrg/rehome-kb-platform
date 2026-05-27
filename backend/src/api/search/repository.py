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

from src.api.articles.models import Article
from src.api.auth.scope import AccessLevel
from src.api.db import get_session
from src.api.search.chunker import Chunk
from src.api.search.models import ArticleEmbedding


@dataclass(frozen=True)
class RetrievalHit:
    """Single retrieved chunk с denormalized article fields для citations."""

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
