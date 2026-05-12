"""articles tags GIN index

Revision ID: 0003_articles_tags_gin_index
Revises: 0002_articles_list_index
Create Date: 2026-05-12 10:05:58.000000

GIN-индекс для JSONB containment-запросов `tags @> '[...]'::jsonb`
(см. Issue #34). Использует opclass `jsonb_path_ops` — меньше index,
быстрее `@>` queries, чем default `jsonb_ops`. Поддерживает только
containment-операцию — нам этого достаточно (нет ?, ?&, ?| queries).

TODO(#26-style EXPLAIN profile): профилировать в production на реальном
трафике — GIN может не использоваться планировщиком, если другие
предикаты (`access_level IN`, `status='PUBLISHED'`) уже отсекают
большую часть строк. Решать после первого реального трафика, не заранее.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_articles_tags_gin_index"
down_revision: str | None = "0002_articles_list_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_articles_tags_gin "
        "ON articles USING gin (tags jsonb_path_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_articles_tags_gin", table_name="articles")
