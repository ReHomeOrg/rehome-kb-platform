"""admin_tasks — universal task registry (#238, OpenAPI §getTaskStatus)

Revision ID: 0024_admin_tasks
Revises: 0024_personal_data_requests
Create Date: 2026-05-23 02:00:00.000000

Универсальный registry для async admin tasks: reindex, audit-log
export, cache_invalidation, eval-runs. Status lifecycle:
PENDING → RUNNING → COMPLETED | FAILED | CANCELLED.

CHECK constraints sync'нутся с `tasks_models.TASK_TYPES /
TASK_STATUSES` через drift test.

Retention: 30 дней (cleanup worker — backlog). На MVP таблица растёт.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024_admin_tasks"
down_revision: str | None = "0024_personal_data_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TYPES = ("reindex", "audit_log_export", "cache_invalidation", "eval_run")
_STATUSES = ("PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")


def _quote_set(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        "admin_tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column(
            "progress_percent",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("result_url", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("actor_sub", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            f"type IN ({_quote_set(_TYPES)})",
            name="ck_admin_tasks_type",
        ),
        sa.CheckConstraint(
            f"status IN ({_quote_set(_STATUSES)})",
            name="ck_admin_tasks_status",
        ),
        sa.CheckConstraint(
            "progress_percent BETWEEN 0 AND 100",
            name="ck_admin_tasks_progress_range",
        ),
        sa.CheckConstraint(
            "(completed_at IS NULL AND status IN ('PENDING', 'RUNNING')) "
            "OR (completed_at IS NOT NULL AND status IN "
            "('COMPLETED', 'FAILED', 'CANCELLED'))",
            name="ck_admin_tasks_completed_at_consistency",
        ),
    )
    # Admin list: «всё что бежит сейчас».
    op.create_index(
        "ix_admin_tasks_active",
        "admin_tasks",
        ["created_at"],
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING')"),
    )
    # Recent tasks (cleanup window).
    op.create_index(
        "ix_admin_tasks_created",
        "admin_tasks",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_tasks_created", table_name="admin_tasks")
    op.drop_index("ix_admin_tasks_active", table_name="admin_tasks")
    op.drop_table("admin_tasks")
