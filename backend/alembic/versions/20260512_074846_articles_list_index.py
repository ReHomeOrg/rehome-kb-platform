"""articles list composite index

Revision ID: 0002_articles_list_index
Revises: 0001_initial_articles
Create Date: 2026-05-12 07:48:46.000000

Композитный индекс `(updated_at DESC, id DESC)` для keyset-пагинации
list-endpoint'а (см. Issue #25). Без него `ORDER BY updated_at DESC, id
DESC LIMIT N` делает full table scan + sort, что O(N log N).

TODO(#26): в production профилировать EXPLAIN на реальных запросах с
`WHERE category=...` — возможно, планировщик предпочтёт `ix_articles_
status_access_level` и проигнорирует этот индекс; тогда понадобится
композит `(category, updated_at DESC, id DESC)`. Решать после первого
реального трафика, не заранее.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_articles_list_index"
down_revision: str | None = "0001_initial_articles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres-specific: `DESC` direction matters для keyset-сканов,
    # планировщик не разворачивает индекс автоматически в обратную сторону
    # для row-value comparison.
    op.execute(
        "CREATE INDEX ix_articles_updated_at_id "
        "ON articles (updated_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_articles_updated_at_id", table_name="articles")
