"""vault foundation — zero-knowledge tables (#146, ADR-0011)

Revision ID: 0016_vault_foundation
Revises: 0015_premises_cards
Create Date: 2026-05-14 02:00:00.000000

Foundation tables для kb-vault менеджера паролей. Zero-knowledge:
сервер хранит encrypted blobs + metadata, plaintext недоступен.

Tables:
- `vault_users` — per-user crypto state (Argon2id salt, auth hash,
  encrypted X25519 privkey, public X25519 key, encrypted TOTP secret)
- `vault_groups` + `vault_group_members` — collections + membership
- `vault_secrets` — secret metadata + encrypted title (даже title
  hidden в zero-knowledge)
- `vault_secret_wraps` — per-recipient wrapped secret keys
  (user или group)
- `vault_secret_blobs` — encrypted payload (separate table — иначе
  большой ciphertext blot'ит metadata reads)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_vault_foundation"
down_revision: str | None = "0015_premises_cards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # vault_users — per-user crypto state.
    # user_id matches Keycloak sub (UUID). Не FK — Keycloak users в
    # отдельной DB (см. ADR-0007). PK guarantees uniqueness.
    op.create_table(
        "vault_users",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Argon2id salt — 16 random bytes server-generated при first
        # setup. Sent to client при unlock для key derivation.
        sa.Column("argon_salt", sa.LargeBinary(16), nullable=False),
        # auth_hash — HKDF output от master_key с info='vault-auth'.
        # Server проверяет identity; не позволяет расшифровать secrets.
        sa.Column("auth_hash", sa.LargeBinary(32), nullable=False),
        # Encrypted X25519 privkey + plaintext pubkey. Privkey
        # wrapped vault_key (client-only); pubkey используется для
        # group sharing (асимметричный sealed_box).
        sa.Column("encrypted_x25519_privkey", sa.LargeBinary, nullable=False),
        sa.Column("x25519_pubkey", sa.LargeBinary(32), nullable=False),
        # TOTP secret encrypted under vault_key. NULL до 2FA setup.
        sa.Column("totp_secret_encrypted", sa.LargeBinary, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_unlock_at", sa.DateTime(timezone=True), nullable=True),
    )

    # vault_groups — collections (по командам / типам секретов).
    op.create_table(
        "vault_groups",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_vault_groups_name", "vault_groups", ["name"])

    # vault_group_members — membership; роль для admin-actions.
    op.create_table(
        "vault_group_members",
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'member')",
            name="ck_vault_group_members_role",
        ),
    )
    op.create_index(
        "ix_vault_group_members_user",
        "vault_group_members",
        ["user_id"],
    )

    # vault_secrets — metadata + encrypted title.
    op.create_table(
        "vault_secrets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Title encrypted (zero-knowledge — даже название не утечёт).
        sa.Column("title_ciphertext", sa.LargeBinary, nullable=False),
        # Category — plaintext, для filter / list grouping. Не sensitive
        # (см. PZ §8.2 — категории это server / db / payments / etc.).
        sa.Column("category", sa.String(64), nullable=False),
        # owner_id — кто отвечает за актуальность секрета (PZ §8.3).
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # expires_at — rotation reminders worker scans expired entries.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_vault_secrets_owner", "vault_secrets", ["owner_id"])
    op.create_index("ix_vault_secrets_category", "vault_secrets", ["category"])
    op.create_index(
        "ix_vault_secrets_expires_at",
        "vault_secrets",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL AND archived_at IS NULL"),
    )

    # vault_secret_wraps — per-recipient wrapped secret keys.
    # EXACTLY ONE of (user_id, group_id) populated — CHECK enforce'ит.
    op.create_table(
        "vault_secret_wraps",
        sa.Column(
            "secret_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_secrets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_groups.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("wrapped_key", sa.LargeBinary, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # Composite PK — (secret_id, user_id, group_id). NULL coalesce
        # для PK не работает напрямую — используем UNIQUE индексы
        # по двум sub-paths.
        sa.PrimaryKeyConstraint(
            "secret_id",
            "user_id",
            "group_id",
            name="pk_vault_secret_wraps",
        ),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND group_id IS NULL) "
            "OR (user_id IS NULL AND group_id IS NOT NULL)",
            name="ck_vault_secret_wraps_xor",
        ),
    )
    op.create_index(
        "ix_vault_secret_wraps_user",
        "vault_secret_wraps",
        ["user_id"],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_vault_secret_wraps_group",
        "vault_secret_wraps",
        ["group_id"],
        postgresql_where=sa.text("group_id IS NOT NULL"),
    )

    # vault_secret_blobs — encrypted payload separately от metadata.
    # 1:1 с secrets; отдельная table чтобы metadata-scan'ы (list,
    # owner filter) не загружали потенциально большие blob'ы.
    op.create_table(
        "vault_secret_blobs",
        sa.Column(
            "secret_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vault_secrets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("ciphertext", sa.LargeBinary, nullable=False),
        # payload_version — monotonic для concurrent-edit detection.
        # Client отправляет expected version при PUT; server отклонит
        # если != current (lost-update prevention).
        sa.Column(
            "payload_version",
            sa.Integer,
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("vault_secret_blobs")
    op.drop_index("ix_vault_secret_wraps_group", table_name="vault_secret_wraps")
    op.drop_index("ix_vault_secret_wraps_user", table_name="vault_secret_wraps")
    op.drop_table("vault_secret_wraps")
    op.drop_index("ix_vault_secrets_expires_at", table_name="vault_secrets")
    op.drop_index("ix_vault_secrets_category", table_name="vault_secrets")
    op.drop_index("ix_vault_secrets_owner", table_name="vault_secrets")
    op.drop_table("vault_secrets")
    op.drop_index("ix_vault_group_members_user", table_name="vault_group_members")
    op.drop_table("vault_group_members")
    op.drop_index("ix_vault_groups_name", table_name="vault_groups")
    op.drop_table("vault_groups")
    op.drop_table("vault_users")
