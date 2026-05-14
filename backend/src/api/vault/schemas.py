"""Pydantic schemas для kb-vault (#147).

Zero-knowledge: все sensitive fields передаются как base64-encoded
bytes (HTTP не позволяет raw binary в JSON). Server валидирует size
boundaries — но не семантику ciphertext.

Base64 encode для UTF-8 совместимости. JSON-friendly representation;
backend decode → bytes для DB persistence.
"""

from base64 import b64decode
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.vault.models import (
    VaultGroup,
    VaultSecret,
    VaultSecretBlob,
    VaultUser,
)

# Размер ciphertext'а ограничен — anti-DoS guard. 64 KiB достаточно для
# секрета (URL + login + password + TOTP + notes + recovery codes), но
# защищает от abuse'а через гигантские blob'ы.
MAX_TITLE_CIPHERTEXT_BYTES = 4 * 1024  # 4 KiB — title никогда не большой
MAX_BLOB_CIPHERTEXT_BYTES = 64 * 1024
MAX_WRAPPED_KEY_BYTES = 256  # X25519 sealed_box ~48b, master wrap ~64b
MAX_PUBKEY_BYTES = 32  # X25519 pubkey
MAX_ENCRYPTED_PRIVKEY_BYTES = 256


def _decode_b64(value: str, max_len: int, field_name: str) -> bytes:
    """Decode base64 + validate length.

    Raises ValueError на malformed b64 или превышение `max_len`.
    Pydantic ловит ValueError и возвращает 422.
    """
    try:
        decoded = b64decode(value, validate=True)
    except Exception as exc:
        raise ValueError(f"{field_name}: malformed base64") from exc
    if len(decoded) > max_len:
        raise ValueError(f"{field_name}: ciphertext exceeds {max_len} bytes")
    if not decoded:
        raise ValueError(f"{field_name}: empty after decode")
    return decoded


# ---------------------------------------------------------------------------
# Setup / unlock


class VaultSetupInput(BaseModel):
    """Initial vault setup: client deriv'ит crypto state, server stores.

    Auth_hash — НЕ master password. Это HKDF output от master_key с
    info='vault-auth'. Server не может derive vault_key из auth_hash.
    """

    model_config = ConfigDict(extra="forbid")

    argon_salt_b64: str
    auth_hash_b64: str
    encrypted_x25519_privkey_b64: str
    x25519_pubkey_b64: str

    @field_validator("argon_salt_b64")
    @classmethod
    def _v_salt(cls, v: str) -> str:
        _decode_b64(v, 16, "argon_salt")  # exactly 16 bytes
        return v

    @field_validator("auth_hash_b64")
    @classmethod
    def _v_auth(cls, v: str) -> str:
        _decode_b64(v, 32, "auth_hash")
        return v

    @field_validator("encrypted_x25519_privkey_b64")
    @classmethod
    def _v_privkey(cls, v: str) -> str:
        _decode_b64(v, MAX_ENCRYPTED_PRIVKEY_BYTES, "encrypted_x25519_privkey")
        return v

    @field_validator("x25519_pubkey_b64")
    @classmethod
    def _v_pubkey(cls, v: str) -> str:
        _decode_b64(v, MAX_PUBKEY_BYTES, "x25519_pubkey")
        return v


class VaultUnlockInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auth_hash_b64: str

    @field_validator("auth_hash_b64")
    @classmethod
    def _v(cls, v: str) -> str:
        _decode_b64(v, 32, "auth_hash")
        return v


class VaultMeView(BaseModel):
    """GET /vault/me — текущее crypto state пользователя.

    Опциональные поля = vault не setup'нут (initial setup needed).
    Server-side data только: salt + pubkey + encrypted_privkey + 2FA
    bit. auth_hash НЕ возвращается (anti-replay).
    """

    model_config = ConfigDict(from_attributes=False)

    is_setup: bool
    argon_salt_b64: str | None = None
    x25519_pubkey_b64: str | None = None
    encrypted_x25519_privkey_b64: str | None = None
    has_totp: bool = False
    last_unlock_at: datetime | None = None


class VaultUnlockResponse(BaseModel):
    """Unlock success → server возвращает 200 (для anti-bruteforce).

    Никакого session token'а — JWT Keycloak'а сам по себе достаточен.
    Client решает локально когда re-prompt'ить master password (15min
    idle timer client-side).
    """

    success: bool = True


# ---------------------------------------------------------------------------
# Secrets


class VaultSecretWrapInput(BaseModel):
    """Per-recipient wrap при создании / share секрета.

    EXACTLY ONE of (user_id, group_id) указан.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None = None
    group_id: UUID | None = None
    wrapped_key_b64: str

    @field_validator("wrapped_key_b64")
    @classmethod
    def _v_wrap(cls, v: str) -> str:
        _decode_b64(v, MAX_WRAPPED_KEY_BYTES, "wrapped_key")
        return v


class VaultSecretCreateInput(BaseModel):
    """POST /vault/secrets — create encrypted secret + wraps."""

    model_config = ConfigDict(extra="forbid")

    title_ciphertext_b64: str
    category: str = Field(min_length=1, max_length=64)
    blob_ciphertext_b64: str
    wraps: list[VaultSecretWrapInput] = Field(min_length=1)
    expires_at: datetime | None = None

    @field_validator("title_ciphertext_b64")
    @classmethod
    def _v_title(cls, v: str) -> str:
        _decode_b64(v, MAX_TITLE_CIPHERTEXT_BYTES, "title_ciphertext")
        return v

    @field_validator("blob_ciphertext_b64")
    @classmethod
    def _v_blob(cls, v: str) -> str:
        _decode_b64(v, MAX_BLOB_CIPHERTEXT_BYTES, "blob_ciphertext")
        return v


class VaultSecretUpdateInput(BaseModel):
    """PUT /vault/secrets/{id} — update encrypted blob.

    `expected_version` — client'ом отслеживаемая monotonic версия. Server
    отклонит update если current version mismatch'ит (lost-update prevention).
    """

    model_config = ConfigDict(extra="forbid")

    blob_ciphertext_b64: str
    expected_version: int = Field(ge=1)

    @field_validator("blob_ciphertext_b64")
    @classmethod
    def _v(cls, v: str) -> str:
        _decode_b64(v, MAX_BLOB_CIPHERTEXT_BYTES, "blob_ciphertext")
        return v


class VaultSecretMetadataView(BaseModel):
    """Metadata-only view (для list endpoint).

    title_ciphertext возвращается — клиент decrypt'ит сам.
    blob ciphertext НЕ возвращается (separate detail endpoint).
    """

    model_config = ConfigDict(from_attributes=False)

    id: UUID
    title_ciphertext_b64: str
    category: str
    owner_id: UUID
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    archived_at: datetime | None = None


class VaultSecretView(VaultSecretMetadataView):
    """Detail view — metadata + blob + caller's wrapped key.

    Каждый recipient (user или group member) имеет свой wrapped_key,
    зашифрованный соответствующим pubkey. Сервер выбирает первый match
    для caller'а (user_id wrap > group wrap).
    """

    blob_ciphertext_b64: str
    payload_version: int
    wrapped_key_b64: str
    # Если wrap пришёл через group — указано какую (для UI rendering).
    via_group_id: UUID | None = None


# ---------------------------------------------------------------------------
# Groups


class VaultGroupCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class VaultGroupView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None = None
    created_by: UUID
    created_at: datetime


class VaultGroupListResponse(BaseModel):
    data: list[VaultGroupView]


# ---------------------------------------------------------------------------
# Group members (#155)


class VaultGroupMemberAddInput(BaseModel):
    """Body для POST /vault/groups/{id}/members.

    `role` — 'owner' | 'member'. Default 'member' защищает от случайного
    privilege escalation (нужен явный 'owner').
    """

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    role: str = Field(default="member", pattern=r"^(owner|member)$")


class VaultGroupMemberView(BaseModel):
    """Membership row для list endpoint."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    group_id: UUID
    user_id: UUID
    role: str
    added_at: datetime


class VaultGroupMemberListResponse(BaseModel):
    data: list[VaultGroupMemberView]


class VaultSecretListResponse(BaseModel):
    data: list[VaultSecretMetadataView]


# ---------------------------------------------------------------------------
# View builders


def me_view_from_user(user: VaultUser | None) -> VaultMeView:
    """Build /vault/me response из ORM VaultUser (или None если не setup'нут)."""
    if user is None:
        return VaultMeView(is_setup=False)
    from base64 import b64encode

    return VaultMeView(
        is_setup=True,
        argon_salt_b64=b64encode(user.argon_salt).decode("ascii"),
        x25519_pubkey_b64=b64encode(user.x25519_pubkey).decode("ascii"),
        encrypted_x25519_privkey_b64=b64encode(user.encrypted_x25519_privkey).decode("ascii"),
        has_totp=user.totp_secret_encrypted is not None,
        last_unlock_at=user.last_unlock_at,
    )


def secret_metadata_view(secret: VaultSecret) -> VaultSecretMetadataView:
    from base64 import b64encode

    return VaultSecretMetadataView(
        id=secret.id,
        title_ciphertext_b64=b64encode(secret.title_ciphertext).decode("ascii"),
        category=secret.category,
        owner_id=secret.owner_id,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
        expires_at=secret.expires_at,
        archived_at=secret.archived_at,
    )


def secret_detail_view(
    secret: VaultSecret,
    blob: VaultSecretBlob,
    wrapped_key: bytes,
    via_group_id: UUID | None,
) -> VaultSecretView:
    from base64 import b64encode

    return VaultSecretView(
        id=secret.id,
        title_ciphertext_b64=b64encode(secret.title_ciphertext).decode("ascii"),
        category=secret.category,
        owner_id=secret.owner_id,
        created_at=secret.created_at,
        updated_at=secret.updated_at,
        expires_at=secret.expires_at,
        archived_at=secret.archived_at,
        blob_ciphertext_b64=b64encode(blob.ciphertext).decode("ascii"),
        payload_version=blob.payload_version,
        wrapped_key_b64=b64encode(wrapped_key).decode("ascii"),
        via_group_id=via_group_id,
    )


def group_view(group: VaultGroup) -> VaultGroupView:
    return VaultGroupView.model_validate(group)


# Re-export для test imports.
__all__ = [
    "MAX_BLOB_CIPHERTEXT_BYTES",
    "MAX_ENCRYPTED_PRIVKEY_BYTES",
    "MAX_PUBKEY_BYTES",
    "MAX_TITLE_CIPHERTEXT_BYTES",
    "MAX_WRAPPED_KEY_BYTES",
    "VaultGroupCreateInput",
    "VaultGroupListResponse",
    "VaultGroupView",
    "VaultMeView",
    "VaultSecretCreateInput",
    "VaultSecretListResponse",
    "VaultSecretMetadataView",
    "VaultSecretUpdateInput",
    "VaultSecretView",
    "VaultSecretWrapInput",
    "VaultSetupInput",
    "VaultUnlockInput",
    "VaultUnlockResponse",
    "group_view",
    "me_view_from_user",
    "secret_detail_view",
    "secret_metadata_view",
]
