"""ArticleEmbedding ORM model (kb-search Stage 1, ADR-0010 #126).

Один row на (article_id, chunk_index, embedding_model_id). PK включает
`embedding_model_id` для blue-green re-embedding (ADR-0010 §"Re-embedding
на model bump"): new model adds rows под new `embedding_model_id` без
удаления old, atomic switch когда coverage 100%.

ADR-0003: chunks НЕ хранят свой `access_level` напрямую — они inherit от
parent article'а через FK. Retrieval filter JOIN'ит articles по
`access_level IN (...)`. Это устраняет двойной truth: access changes
на article уровне propagate'ятся в RAG queries автоматически.
"""

from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class ArticleEmbedding(Base):
    """Vector embedding chunk'а статьи."""

    __tablename__ = "article_embeddings"

    article_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )
    # Версия embedding-модели — часть PK для blue-green re-embedding
    # (ADR-0010 §"Re-embedding на model bump"). Default — current model
    # из Settings.embedding_model, но column сам hardcode-safe.
    embedding_model_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )
    # Vector dimension matches Settings.embedding_dim. Изменение dim требует
    # migration (column type) — это inherent ограничение pgvector.
    embedding: Mapped[list[float]] = mapped_column(
        Vector(1024),
        nullable=False,
    )
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # HNSW index создаётся в миграции (`__table_args__` SQLAlchemy не
    # поддерживает pgvector-specific index types напрямую — operator
    # class `vector_cosine_ops` + WITH params задаём explicit'ly в SQL).
    # Так же index на `(article_id, embedding_model_id)` для model bump
    # scans — пишется в миграции.
    __table_args__ = ({"comment": "article chunk embeddings (ADR-0010, #126)"},)

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return (
            f"<ArticleEmbedding article_id={self.article_id} "
            f"chunk_index={self.chunk_index} model={self.embedding_model_id!r}>"
        )
