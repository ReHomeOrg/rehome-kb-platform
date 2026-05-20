"""vault_fido2_credentials — FIDO2/WebAuthn credentials (ADR-0022 A)

Revision ID: 0025_vault_fido2
Revises: 0024_system_config
Create Date: 2026-05-24 01:00:00.000000

Per ADR-0022 Вариант A: FIDO2 заменяет TOTP. Existing TOTP-users
grandfathered (отдельный VaultUser.totp_secret_encrypted column
остаётся); new setups только FIDO2.

Schema:
- `id` — surrogate UUID PK (для DELETE /credentials/{id}).
- `user_id` — FK на vault_users.user_id (Keycloak sub).
- `credential_id` — WebAuthn credentialID (bytea, unique). Authenticator-
  generated handle, 16-1024 bytes typical.
- `public_key` — CBOR-encoded COSE_Key (bytea). Verification material.
- `sign_count` — monotonic counter, incremented по каждому
  successful assertion. Replay-attack detection: новый assertion с
  sign_count <= last_seen → security_incident.
- `transports` — JSONB array WebAuthn transports («usb», «nfc», «ble»,
  «internal», «hybrid»). Используется для assertion hints.
- `aaguid` — Authenticator Attestation GUID (bytea(16)), nullable.
  Identifies authenticator model. Stored для security analysis.
- `nickname` — user-assigned label («YubiKey 5C», «MacBook Touch ID»).

Indexes:
- Unique на `credential_id` — WebAuthn spec required.
- На `user_id` — list/lookup per user (≤5 rows).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025_vault_fido2"
down_revision: str | None = "0024_system_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vault_fido2_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False, unique=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "transports",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("aaguid", sa.LargeBinary(length=16), nullable=True),
        sa.Column("nickname", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_vault_fido2_credentials_user",
        "vault_fido2_credentials",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vault_fido2_credentials_user",
        table_name="vault_fido2_credentials",
    )
    op.drop_table("vault_fido2_credentials")
