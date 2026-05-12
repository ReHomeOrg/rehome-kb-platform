"""categories table

Revision ID: 0007_categories_table
Revises: 0006_articles_search_vector
Create Date: 2026-05-12 14:00:00.000000

Normalized таблица категорий (Issue #54) с self-referential parent_id.
Связь с articles — по `articles.category = categories.slug` (string),
без FK constraint на этом этапе (backlog для admin CRUD эпика).

Data migration: для каждой DISTINCT articles.category создаётся root-
запись categories с title=slug.replace('-',' ').capitalize(). Это
гарантирует, что после миграции дерево не пустое (если в articles
уже есть данные).

CHECK constraint `parent_id <> id` — anti-self-reference. Полное
cycle-detection (A→B→A) — backlog.

`ON DELETE RESTRICT` на parent_id FK — нельзя удалить родителя с детьми
(защита от orphan-узлов; admin CRUD должен сначала перевесить детей).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_categories_table"
down_revision: str | None = "0006_articles_search_vector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("categories.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
        sa.CheckConstraint("parent_id <> id", name="ck_categories_no_self_reference"),
    )
    op.create_index("ix_categories_slug", "categories", ["slug"])
    op.create_index(
        "ix_categories_parent_slug", "categories", ["parent_id", "slug"]
    )

    # Data migration: seed root-categories из DISTINCT articles.category.
    # `INITCAP` (capitalize words) + replace '-' → ' ' даёт читабельный
    # title из slug ('servisnyy-platej' → 'Servisnyy Platej'). Для
    # admin CRUD эпика — переименовать на корректное.
    op.execute(
        """
        INSERT INTO categories (slug, title)
        SELECT DISTINCT
            a.category AS slug,
            INITCAP(REPLACE(a.category, '-', ' ')) AS title
        FROM articles a
        WHERE a.category IS NOT NULL
        ON CONFLICT (slug) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_categories_parent_slug", table_name="categories")
    op.drop_index("ix_categories_slug", table_name="categories")
    op.drop_table("categories")
