"""SQLAlchemy ORM models для kb-vault (#146, ADR-0011).

Zero-knowledge архитектура: сервер хранит encrypted blobs + metadata,
plaintext недоступен. Все crypto operations — на клиенте.

Tables:
- `VaultUser` — per-user crypto state (salt, auth hash, X25519 keys,
  encrypted TOTP).
- `VaultGroup` + `VaultGroupMember` — sharing collections.
- `VaultSecret` — metadata + encrypted title.
- `VaultSecretWrap` — per-recipient wrapped secret keys (user OR group).
- `VaultSecretBlob` — encrypted payload (separate table от metadata
  scans).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class VaultUser(Base):
    """Per-user crypto state. `user_id` matches Keycloak sub."""

    __tablename__ = "vault_users"

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    argon_salt: Mapped[bytes] = mapped_column(LargeBinary(16), nullable=False)
    auth_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    encrypted_x25519_privkey: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    x25519_pubkey: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_unlock_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VaultGroup(Base):
    """Sharing collection (например, team или secret-category)."""

    __tablename__ = "vault_groups"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_vault_groups_name", "name"),)


class VaultGroupMember(Base):
    """Membership + role. CHECK на role: 'owner' | 'member'."""

    __tablename__ = "vault_group_members"

    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vault_groups.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="member")
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'member')",
            name="ck_vault_group_members_role",
        ),
        Index("ix_vault_group_members_user", "user_id"),
    )


class VaultSecret(Base):
    """Secret metadata + encrypted title (zero-knowledge — даже title hidden)."""

    __tablename__ = "vault_secrets"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    title_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_vault_secrets_owner", "owner_id"),
        Index("ix_vault_secrets_category", "category"),
    )


class VaultSecretWrap(Base):
    """Per-recipient wrapped secret key (ADR-0017).

    `user_id` — recipient (всегда NOT NULL после migration 0023). Wrap
    зашифрован под user.x25519_pubkey.

    `group_id` — **lineage metadata**: «этот wrap был создан в рамках
    шаринга с группой G». Не используется для authorization (только
    user_id). Может быть NULL (personal wrap либо direct share).

    Sharing с группой ⇒ N rows (по одной на каждого member'а), всех
    с одинаковым `group_id` lineage.
    """

    __tablename__ = "vault_secret_wraps"

    secret_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vault_secrets.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    group_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vault_groups.id", ondelete="CASCADE"),
        nullable=True,
    )
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (PrimaryKeyConstraint("secret_id", "user_id", name="pk_vault_secret_wraps"),)


class VaultSecretBlob(Base):
    """Encrypted payload — отдельная таблица для metadata-scan efficiency.

    `payload_version` — monotonic counter; client отправляет
    expected version при PUT (lost-update prevention).
    """

    __tablename__ = "vault_secret_blobs"

    secret_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vault_secrets.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class VaultFIDO2Credential(Base):
    """FIDO2 / WebAuthn credential per-key (ADR-0022 A).

    Один user может иметь до 5 registered keys (primary + backups).
    `credential_id` — authenticator-generated handle, unique globally.
    `sign_count` — monotonic counter для replay-attack detection;
    increment per successful assertion (если incoming count <= stored,
    тригерим security_incident).
    """

    __tablename__ = "vault_fido2_credentials"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vault_users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    transports: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    aaguid: Mapped[bytes | None] = mapped_column(LargeBinary(16), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_vault_fido2_credentials_user", "user_id"),)
