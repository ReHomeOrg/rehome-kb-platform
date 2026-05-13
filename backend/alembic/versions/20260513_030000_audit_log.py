"""audit_log table

Revision ID: 0013_audit_log
Revises: 0012_webhook_deliveries
Create Date: 2026-05-13 03:00:00.000000

Transactional compliance trail (ФЗ-152) — E4.x #102.

Один row на одно write-действие (article create/update/archive, webhook
create/delete, etc.). INSERT в той же транзакции, что и trigger →
at-least-once гарантия audit-trail'а.

INDICES:
- `(actor_sub, created_at DESC)` — admin lookup "что делал user X".
- `(resource_type, resource_id, created_at DESC)` — forensic /
  Subject Access Request "кто менял resource Y".

ФЗ-152: invariant — `metadata` JSONB НЕ содержит content / PII.
Enforce'ится на application-layer (см. `audit/repository.py` docstring).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_audit_log"
down_revision: str | None = "0012_webhook_deliveries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("actor_sub", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_audit_log_actor_created",
        "audit_log",
        ["actor_sub", "created_at"],
    )
    op.create_index(
        "ix_audit_log_resource_created",
        "audit_log",
        ["resource_type", "resource_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_resource_created", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_created", table_name="audit_log")
    op.drop_table("audit_log")
