"""Merge alembic 0024 heads (search_query_log + kb_users)

Revision ID: 0024_merge_heads
Revises: 0024_search_query_log, 0024_kb_users
Create Date: 2026-05-19 12:00:00.000000

Two unrelated 0024_* migrations landed concurrently из feature branches
(PR #266 + PR #276). Alembic ругается `Multiple head revisions`. Этот
merge revision реализует no-op DDL — только unifies head linage.
"""

from collections.abc import Sequence

revision: str = "0024_merge_heads"
down_revision: str | Sequence[str] | None = (
    "0024_search_query_log",
    "0024_kb_users",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
