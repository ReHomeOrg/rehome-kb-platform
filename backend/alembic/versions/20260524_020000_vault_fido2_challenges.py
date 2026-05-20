"""vault_fido2_challenges — WebAuthn ceremony state (ADR-0022 A)

Revision ID: 0026_vault_fido2_challenges
Revises: 0025_vault_fido2
Create Date: 2026-05-24 02:00:00.000000

WebAuthn ceremony (registration + authentication) is two-step:
  1. begin — server generates random challenge + options, sends to client.
  2. complete — client returns authenticator-signed response; server
     verifies signature against the SAME challenge.

Need server-side challenge storage to link begin → complete. Schema:

- `challenge` bytea PRIMARY KEY — py_webauthn generates 64 random bytes;
  collision risk negligible.
- `user_id` UUID — owner (anti-cross-user replay).
- `ceremony` text — 'registration' | 'authentication'.
- `expires_at` timestamptz — TTL (5 min default; ceremony done в seconds,
  expired rows reaped). NB: ceremony.complete deletes the row on success,
  so storage scales с error rate, not throughput.

No FK on user_id — vault_users.user_id может ещё не существовать на
момент первой registration ceremony (challenge issued до создания vault).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_vault_fido2_challenges"
down_revision: str | None = "0025_vault_fido2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vault_fido2_challenges",
        sa.Column("challenge", sa.LargeBinary(), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ceremony", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "ceremony IN ('registration', 'authentication')",
            name="ck_vault_fido2_challenges_ceremony",
        ),
    )
    op.create_index(
        "ix_vault_fido2_challenges_user",
        "vault_fido2_challenges",
        ["user_id"],
    )
    op.create_index(
        "ix_vault_fido2_challenges_expires_at",
        "vault_fido2_challenges",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vault_fido2_challenges_expires_at",
        table_name="vault_fido2_challenges",
    )
    op.drop_index(
        "ix_vault_fido2_challenges_user",
        table_name="vault_fido2_challenges",
    )
    op.drop_table("vault_fido2_challenges")
