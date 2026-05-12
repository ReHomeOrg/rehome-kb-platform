"""webhooks table

Revision ID: 0011_webhooks
Revises: 0010_chat_escalations
Create Date: 2026-05-13 01:00:00.000000

Webhook subscriptions foundation (E5.1 #87).

Storage:
- `client_id` — Keycloak `sub` (owner). Каждый client видит только
  свои webhooks (owner-scoped filter в repository).
- `events` TEXT[] — Postgres array, CHECK на non-empty.
- `secret` — HMAC key (generate если не передан). Stripe-like signing
  через `x-rehome-signature` header в E5.2 delivery worker.
- `last_delivery_*` — обновляются delivery worker'ом (E5.2).
- `deleted_at` — soft-delete (отозвать без потери истории).

INDICES:
- `(client_id) WHERE deleted_at IS NULL` partial — для list-by-owner.

Backlog:
- Outbox event recording — E5.2.
- Per-event subscription matching — E5.4.
- POST /webhooks/{id}/test endpoint — E5.2.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_webhooks"
down_revision: str | None = "0010_chat_escalations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhooks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "events",
            postgresql.ARRAY(sa.String()),
            nullable=False,
        ),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_status", sa.Integer(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "array_length(events, 1) >= 1",
            name="ck_webhooks_events_not_empty",
        ),
    )
    op.create_index("ix_webhooks_client_id", "webhooks", ["client_id"])
    op.create_index(
        "ix_webhooks_client_alive",
        "webhooks",
        ["client_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_webhooks_client_alive", table_name="webhooks")
    op.drop_index("ix_webhooks_client_id", table_name="webhooks")
    op.drop_table("webhooks")
