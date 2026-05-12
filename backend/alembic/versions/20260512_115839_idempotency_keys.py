"""idempotency_keys table

Revision ID: 0005_idempotency_keys
Revises: 0004_article_versions
Create Date: 2026-05-12 11:58:39.000000

Таблица для retry-safety POST /articles (E5.1 #44, OpenAPI IdempotencyKey).
Клиент при retry отправляет тот же `Idempotency-Key: <UUID>` → сервер
replay'ит cached response вместо повторного создания.

PK (key, request_path, actor_sub):
- key — UUID from client.
- request_path — позволяет тот же key для разных endpoint'ов.
- actor_sub — Keycloak `sub`; защита от cross-actor leakage.

TTL = 24h (per OpenAPI). Cleanup expired entries — backlog (E5.x cron job).
Index on expires_at — для будущего pruning.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_idempotency_keys"
down_revision: str | None = "0004_article_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("request_path", sa.String(length=500), nullable=False),
        sa.Column("actor_sub", sa.String(length=255), nullable=False),
        sa.Column("request_body_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column(
            "response_body",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "response_headers",
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
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "key", "request_path", "actor_sub", name="pk_idempotency_keys"
        ),
    )
    op.create_index(
        "ix_idempotency_keys_expires_at",
        "idempotency_keys",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_idempotency_keys_expires_at", table_name="idempotency_keys"
    )
    op.drop_table("idempotency_keys")
