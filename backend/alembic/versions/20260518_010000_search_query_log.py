"""search_query_log — лог поисковых запросов для popular_query event

Revision ID: 0024_search_query_log
Revises: 0023_vault_wraps_multi_user
Create Date: 2026-05-18 01:00:00.000000

Лог поисковых запросов для daily aggregation `search.popular_query`
webhook event (ТЗ §5.1: «Запрос стал часто повторяющимся без ответа
(раз в день)»). Записывается из `POST /api/v1/search` router'а.

Storage:
- `query_normalized` — `lower(strip(q))`, для group-by. Raw `q` не
  сохраняем (PII anti-pattern: пользователь мог вбить «иванов договор»).
- `has_results` — true если retrieval вернул ≥ 1 hit. Aggregator группирует
  по `query_normalized WHERE has_results=false`.
- `created_at` — для time-window filter (`>= now() - interval '24 hours'`).

INDICES:
- `(created_at) WHERE has_results = false` partial — covering для
  aggregator scan (typical window 24h, large date span filter'ится out).
- `(query_normalized, created_at)` — секондарный, для individual query
  history lookup (debug / admin tool).

Retention:
- Cleanup — backlog. MVP: оставляем расти; на 1M rows ~ 200MB. Daily
  worker может потом truncate'ить `< now() - interval '90 days'`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024_search_query_log"
down_revision: str | None = "0023_vault_wraps_multi_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "search_query_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("query_normalized", sa.String(length=500), nullable=False),
        sa.Column("has_results", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(query_normalized) >= 1",
            name="ck_search_query_log_query_not_empty",
        ),
    )
    # Partial index: aggregator интересуют только unanswered queries.
    # Делает 24h scan O(matched rows) вместо O(table).
    op.create_index(
        "ix_search_query_log_unanswered_recent",
        "search_query_log",
        ["created_at"],
        postgresql_where=sa.text("has_results = false"),
    )
    # Secondary: history lookup для одного query (debug).
    op.create_index(
        "ix_search_query_log_query_created",
        "search_query_log",
        ["query_normalized", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_search_query_log_query_created", table_name="search_query_log")
    op.drop_index("ix_search_query_log_unanswered_recent", table_name="search_query_log")
    op.drop_table("search_query_log")
