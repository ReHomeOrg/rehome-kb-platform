"""categories.archived_at column для soft-delete (#355, ADR-0024)

Revision ID: 0030_categories_archived_at
Revises: 0029_articles_tags_lowercase
Create Date: 2026-05-25 01:00:00.000000

Adds `archived_at TIMESTAMPTZ NULL` column to `categories` table — per
ADR-0024 Вариант B (soft-delete вместо hard-delete с RESTRICT FK на
articles.category). Existing rows получают NULL (active). Admin
soft-delete устанавливает archived_at = now().

Partial index `WHERE archived_at IS NULL` accelerate'ит typical
tree-query (active categories only); существующий
`ix_categories_parent_slug` остаётся для full-table lookups (admin UI
показывает archived с filter toggle).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_categories_archived_at"
down_revision: str | None = "0029_articles_tags_lowercase"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index — only active categories. Used by public `GET /categories`
    # tree query + article_count aggregation.
    op.execute(
        "CREATE INDEX ix_categories_active "
        "ON categories (slug) WHERE archived_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_categories_active", table_name="categories")
    op.drop_column("categories", "archived_at")
