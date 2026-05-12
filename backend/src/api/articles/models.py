"""SQLAlchemy ORM модель Article.

Соответствует OpenAPI `Article` schema (минимальное подмножество для E2.1).
Расширения (body_html-render, history, relationships) — в будущих PR.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class Article(Base):
    """Статья help-центра / внутренней wiki.

    КРИТИЧЕСКИЙ ИНВАРИАНТ ADR-0003: `access_level` — поле обязательное,
    индексированное; все SELECT по этой таблице ДОЛЖНЫ иметь
    `WHERE access_level IN (...)` фильтр.
    """

    __tablename__ = "articles"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    slug: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)

    # OpenAPI Audience enum — храним как строку с CHECK constraint в миграции.
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="ru")
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )

    # KEY ADR-0003 поле — storage-level filter применяется по нему.
    access_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="DRAFT",
        index=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # FTS search vector (E2.5a #46) — Postgres generated STORED column.
    # Stemming через `russian` config; weights: title=A, category=B, body=C.
    # Tags/summary — backlog (см. migration 0006 docstring).
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('russian', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('russian', coalesce(category, '')), 'B') || "
            "setweight(to_tsvector('russian', coalesce(body_markdown, '')), 'C')",
            persisted=True,
        ),
    )

    __table_args__ = (
        # Композитный индекс: типичный запрос фильтрует по status + access_level.
        Index("ix_articles_status_access_level", "status", "access_level"),
    )

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return f"<Article slug={self.slug!r} status={self.status!r}>"

    # Источник истины для enum-значений — OpenAPI schema (docs/handoff/
    # 01_postanovka/04_openapi.yaml: components/schemas/{Audience,
    # ArticleStatus, AccessLevel}). Эти tuple'ы дублируются в CHECK
    # constraint миграции 0001_initial_articles; test_models_check_sync.py
    # гарантирует, что значения не разъедутся.
    @staticmethod
    def allowed_audiences() -> tuple[str, ...]:
        return ("all", "guest", "tenant", "landlord", "agent", "staff")

    @staticmethod
    def allowed_statuses() -> tuple[str, ...]:
        return ("DRAFT", "PUBLISHED", "ARCHIVED")

    @staticmethod
    def allowed_access_levels() -> tuple[str, ...]:
        return ("PUBLIC", "LOGGED", "AGENT", "STAFF", "LEGAL", "HR_RESTRICTED")

    @staticmethod
    def allowed_events() -> tuple[str, ...]:
        """Events для ArticleVersion (E2.3 #36). Sync с CHECK в миграции 0004."""
        return ("CREATE", "UPDATE", "ARCHIVE")

    def to_dict(self) -> dict[str, Any]:
        """Используется в schemas.ArticleResponse.model_validate() через from_attributes."""
        return {
            "id": str(self.id),
            "slug": self.slug,
            "title": self.title,
            "summary": self.summary,
            "body_markdown": self.body_markdown,
            "audience": self.audience,
            "language": self.language,
            "category": self.category,
            "tags": list(self.tags),
            "status": self.status,
            "published_at": self.published_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ArticleVersion(Base):
    """Запись истории изменений Article (E2.3 #36).

    Каждая write-операция (create/update/archive) пишет version-row в
    той же транзакции, что и INSERT/UPDATE articles — атомарно.
    Snapshot тела статьи НЕ хранится (метаданные only); backlog для
    compliance use case.

    Visibility наследуется от parent article через router (404-mask):
    `list_versions` сначала вызывает `get_by_slug`, если scope не видит
    article → None → 404. Отдельного `access_level` у версий нет.
    """

    __tablename__ = "article_versions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    article_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[str] = mapped_column(String(16), nullable=False)
    author_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    old_status: Mapped[str | None] = mapped_column(String(16))
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    old_access_level: Mapped[str | None] = mapped_column(String(20))
    new_access_level: Mapped[str] = mapped_column(String(20), nullable=False)
    changes_summary: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # Sequential numbering per article. Concurrent write при race
        # получит IntegrityError — обрабатывается в repository (backlog E5).
        # Index создаётся в миграции (DESC порядок для query «свежие сверху»).
    )

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return f"<ArticleVersion article_id={self.article_id} v={self.version}>"
