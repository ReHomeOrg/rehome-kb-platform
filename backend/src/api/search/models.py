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
from typing import Final
from uuid import UUID

# pgvector 0.4.0 ships без `py.typed` marker — `# type: ignore[import-untyped]`
# обоснован отсутствием stubs, не misuse'ом API.
from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base

# Stage 1 vector dimension matches `intfloat/multilingual-e5-large` output.
# Same value duplicate'ится в migration 0014 (frozen historical record) и
# Settings.embedding_dim. Изменение требует new migration (column type
# change) — inherent ограничение pgvector.
EMBEDDING_DIM_STAGE1: Final = 1024


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
        Vector(EMBEDDING_DIM_STAGE1),
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


class ArticleQuestionEmbedding(Base):
    """Q&A embedding row (2026-05-29, ТЗ Чат-поиск §«корпуса»).

    Single chunk per (question, model) — Q+A текст короткий, chunking
    не нужен. `text_indexed` материализован после `mask_pii` (raw
    body может содержать ПДн пользователя; persisted masked'ом).

    ADR-0003: access_level inherit'ится через JOIN с article_questions
    → articles в retrieval-side. Здесь не дублируется.
    """

    __tablename__ = "article_question_embeddings"

    article_question_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("article_questions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    embedding_model_id: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIM_STAGE1),
        nullable=False,
    )
    # Хранится материализованно: source rows могли быть masked после
    # indexing'а; reconstruction через JOIN дал бы raw text. Single source
    # of truth для chunk text — этот column.
    text_indexed: Mapped[str] = mapped_column(
        # Text столбец — длинной не фиксируем (Q+A может быть 1-3 абзаца).
        # SQLAlchemy String() без длины → TEXT.
        String(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = ({"comment": "Q&A RAG corpus (ТЗ Чат-поиск, 2026-05-29)"},)

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return (
            f"<ArticleQuestionEmbedding question_id={self.article_question_id} "
            f"model={self.embedding_model_id!r}>"
        )
