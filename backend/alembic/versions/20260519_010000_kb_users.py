"""kb_users — staff registry для admin module (#230, ТЗ OpenAPI §KbUser)

Revision ID: 0024_kb_users
Revises: 0022_collaborator_reviews
Create Date: 2026-05-19 01:00:00.000000

Registry of staff users with kb-module roles (staff_support / staff_legal /
staff_hr / staff_admin). НЕ replaces Keycloak — это metadata layer:
admin создаёт KbUser row для каждого staff'а с extra permissions.

Sync с Keycloak (`last_login_at` update / `mfa_enabled` mirror) —
backlog (нужен Keycloak event listener / scheduled sync). MVP только
admin-managed.

Status lifecycle: ACTIVE → SUSPENDED → ACTIVE (re-activate via PATCH)
или → ARCHIVED (deactivate, soft-delete).

Permissions JSONB array: extra flags поверх role (e.g.
'export_audit_log', 'review_personal_data_requests') — open enumeration
per ТЗ §3.13.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_kb_users"
down_revision: str | None = "0022_collaborator_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ROLES = ("staff_support", "staff_legal", "staff_hr", "staff_admin")
_STATUSES = ("ACTIVE", "SUSPENDED", "ARCHIVED")


def _quote_set(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        "kb_users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "mfa_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.CheckConstraint(
            f"role IN ({_quote_set(_ROLES)})",
            name="ck_kb_users_role",
        ),
        sa.CheckConstraint(
            f"status IN ({_quote_set(_STATUSES)})",
            name="ck_kb_users_status",
        ),
        # Email UNIQUE — каждый staff identity unique. Case-insensitive
        # match через LOWER(email) UNIQUE INDEX ниже (rather than
        # citext extension dependency).
        sa.CheckConstraint(
            "char_length(email) BETWEEN 3 AND 255",
            name="ck_kb_users_email_length",
        ),
    )
    op.create_index(
        "uq_kb_users_email_lower",
        "kb_users",
        [sa.text("lower(email)")],
        unique=True,
    )
    # Cursor pagination — (updated_at DESC, id DESC). Composite index
    # с DESC order для efficient seek.
    op.create_index(
        "ix_kb_users_updated_id",
        "kb_users",
        [sa.text("updated_at DESC"), sa.text("id DESC")],
    )
    # Status filter — partial index на ACTIVE (typical list view).
    op.create_index(
        "ix_kb_users_active",
        "kb_users",
        ["id"],
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )


def downgrade() -> None:
    op.drop_index("ix_kb_users_active", table_name="kb_users")
    op.drop_index("ix_kb_users_updated_id", table_name="kb_users")
    op.drop_index("uq_kb_users_email_lower", table_name="kb_users")
    op.drop_table("kb_users")
