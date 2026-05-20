"""vault emergency access — Shamir 2-of-2 escrow (ADR-0021 A)

Revision ID: 0027_vault_emergency_access
Revises: 0026_vault_fido2_challenges
Create Date: 2026-05-25 01:00:00.000000

Two storage artifacts:

1. `vault_users.escrow_wrap` (nullable bytea) — Encrypt(KEK, escrow_key)
   blob, client-built (AES-GCM nonce+ciphertext+tag). Backend stores
   opaque; никогда не видит escrow_key или KEK.

2. `vault_emergency_unlock_log` — audit/forensic trail каждого emergency
   unlock event. Fields:
   - id UUID PK.
   - user_id UUID — vault owner whose vault was unlocked.
   - requested_by — Keycloak sub admin who initiated.
   - reason_category — enum (5 values per ADR §approve note).
   - reason_text — free-form justification (max 2000 chars).
   - security_incident_id UUID nullable — FK to security_incidents.
   - rkn_notify_required bool — true только для reason_category=incident.
   - created_at timestamptz.

Per ADR-0021 §«audit_log»: каждый emergency unlock — explicit row +
parallel security_incident creation (severity per reason).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0027_vault_emergency_access"
down_revision: str | None = "0026_vault_fido2_challenges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vault_users",
        sa.Column("escrow_wrap", sa.LargeBinary(), nullable=True),
    )

    op.create_table(
        "vault_emergency_unlock_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_users.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("reason_category", sa.String(length=32), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column(
            "security_incident_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "rkn_notify_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "reason_category IN ('incident', 'legal_order', 'employee_departure', "
            "'forensic_audit', 'password_lost')",
            name="ck_vault_emergency_unlock_log_reason_category",
        ),
    )
    op.create_index(
        "ix_vault_emergency_unlock_log_user",
        "vault_emergency_unlock_log",
        ["user_id"],
    )
    op.create_index(
        "ix_vault_emergency_unlock_log_created_at",
        "vault_emergency_unlock_log",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vault_emergency_unlock_log_created_at",
        table_name="vault_emergency_unlock_log",
    )
    op.drop_index(
        "ix_vault_emergency_unlock_log_user",
        table_name="vault_emergency_unlock_log",
    )
    op.drop_table("vault_emergency_unlock_log")
    op.drop_column("vault_users", "escrow_wrap")
