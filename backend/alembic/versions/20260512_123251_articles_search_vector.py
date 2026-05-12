"""articles search_vector generated column + GIN

Revision ID: 0006_articles_search_vector
Revises: 0005_idempotency_keys
Create Date: 2026-05-12 12:32:51.000000

Постgres FTS search (E2.5a #46). Generated STORED column из `title` (weight
A) + `category` (B) + `body_markdown` (C). `russian` config даёт stemming
(«договор» матчит «договоры»).

Weights в `setweight` — приоритет для `ts_rank`: A=1.0, B=0.4, C=0.2, D=0.1.

Tags/summary в search_vector — backlog (требует JSONB array flattening для
tags и null-handling для summary).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_articles_search_vector"
down_revision: str | None = "0005_idempotency_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE articles ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('russian', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('russian', coalesce(category, '')), 'B') ||
            setweight(to_tsvector('russian', coalesce(body_markdown, '')), 'C')
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_articles_search_vector "
        "ON articles USING gin (search_vector)"
    )


def downgrade() -> None:
    op.drop_index("ix_articles_search_vector", table_name="articles")
    op.drop_column("articles", "search_vector")
