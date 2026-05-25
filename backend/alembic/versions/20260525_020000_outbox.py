"""outbox table for transactional webhook dispatch (#356, ADR-0026)

Revision ID: 0031_outbox
Revises: 0030_categories_archived_at
Create Date: 2026-05-25 02:00:00.000000

Transactional outbox pattern (ADR-0026 Slice 0). Slice 1+ переводит
конкретные business writes на atomic commit с outbox.

Schema:
- `id UUID PK` — server_default gen_random_uuid().
- `event_type TEXT NOT NULL` — webhook event identifier (article.published etc.).
- `payload JSONB NOT NULL` — full event payload (subscribers будут receive это).
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` — write moment.
- `flushed_at TIMESTAMPTZ NULL` — drainer marks после успешного fan-out.
- `retries INT NOT NULL DEFAULT 0` — incremented каждый failed drain attempt.
- `last_error TEXT NULL` — last exception detail (truncated; для observability).

Partial index `WHERE flushed_at IS NULL` — drainer query hot path.
Retention 30 days для flushed rows — separate cleanup worker (Slice 3+).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0031_outbox"
down_revision: str | None = "0030_categories_archived_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("flushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "retries",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    # Partial index — drainer hot path: только unflushed rows.
    op.execute(
        "CREATE INDEX ix_outbox_pending ON outbox (created_at) "
        "WHERE flushed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_pending", table_name="outbox")
    op.drop_table("outbox")
