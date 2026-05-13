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

from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_session
from src.api.search.chunker import Chunk
from src.api.search.models import ArticleEmbedding


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
