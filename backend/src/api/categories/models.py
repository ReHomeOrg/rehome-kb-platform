"""SQLAlchemy ORM модель Category.

Self-referential дерево: `parent_id → categories.id` (nullable).
CHECK constraint `parent_id <> id` — anti-self-reference на DB-уровне.
Cycle detection (A→B→A) — app-level в `CategoryAdminRepository`
(ADR-0024). Soft-delete через `archived_at` column (#355).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class Category(Base):
    """Категория в иерархии (Issue #54).

    Связь с Article — по `articles.category = categories.slug` (без FK
    в этом эпике). При несоответствии (articles.category отсутствует в
    categories) счётчик статей в дереве категорий просто игнорирует
    такие записи; категория из articles остаётся «осиротевшей».
    """

    __tablename__ = "categories"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

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
    # Soft-delete (ADR-0024 #355). NULL = active. Public GET /categories
    # filter'ит archived; admin UI показывает с toggle.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint("parent_id <> id", name="ck_categories_no_self_reference"),
        Index("ix_categories_parent_slug", "parent_id", "slug"),
        # Partial index для active-only tree queries (см. migration 0030).
        Index(
            "ix_categories_active",
            "slug",
            postgresql_where="archived_at IS NULL",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return f"<Category slug={self.slug!r} parent_id={self.parent_id!r}>"
