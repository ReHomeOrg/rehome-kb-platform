"""webhook_deliveries table

Revision ID: 0012_webhook_deliveries
Revises: 0011_webhooks
Create Date: 2026-05-13 02:00:00.000000

Outbox для webhook delivery worker (E5.2 #89).

CASCADE на webhook FK: если owner отозвал webhook hard-delete, все
deliveries удаляются. Soft-delete webhook'а оставляет deliveries
(история per ФЗ-152 audit).

INDICES:
- `(next_attempt_at) WHERE status='pending'` partial — worker queue
  poll. Минимизирует size (большинство rows будут delivered).
- `(webhook_id, created_at)` — admin per-webhook listing (E6.x).

CHECK constraint `status ∈ {pending, delivered, failed, dead_letter}`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_webhook_deliveries"
down_revision: str | None = "0011_webhooks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "webhook_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("webhooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'failed', 'dead_letter')",
            name="ck_webhook_deliveries_status",
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_queue",
        "webhook_deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_webhook_deliveries_webhook_created",
        "webhook_deliveries",
        ["webhook_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_deliveries_webhook_created", table_name="webhook_deliveries"
    )
    op.drop_index("ix_webhook_deliveries_queue", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
