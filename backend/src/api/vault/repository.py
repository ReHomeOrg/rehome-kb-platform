"""VaultRepository — opaque storage for zero-knowledge secrets (#146).

Server-side storage layer. Никаких crypto operations здесь — все
ciphertext'ы и ключи передаются клиентом as-is, persist'ятся в БД.

Endpoints (cube 1.2) валидируют ownership / membership через эту
repository; собственно encryption / decryption — на клиенте.

Caller отвечает за commit (consistent с другими репозиториями).
"""

from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_session
from src.api.vault.models import (
    VaultGroup,
    VaultGroupMember,
    VaultSecret,
    VaultSecretBlob,
    VaultSecretWrap,
    VaultUser,
)


class VaultRepository:
    """Storage layer для vault tables. Zero-knowledge — opaque blob CRUD."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -----------------------------------------------------------------
    # VaultUser

    async def get_user(self, user_id: UUID) -> VaultUser | None:
        result = await self._session.execute(select(VaultUser).where(VaultUser.user_id == user_id))
        return result.scalar_one_or_none()

    async def create_user(
        self,
        *,
        user_id: UUID,
        argon_salt: bytes,
        auth_hash: bytes,
        encrypted_x25519_privkey: bytes,
        x25519_pubkey: bytes,
    ) -> VaultUser:
        """Initial setup при первом vault-unlock'е пользователя.

        Idempotency на uniqueness PK — если row уже есть, INSERT
        падает с IntegrityError; caller должен предварительно
        проверить через `get_user`.
        """
        user = VaultUser(
            user_id=user_id,
            argon_salt=argon_salt,
            auth_hash=auth_hash,
            encrypted_x25519_privkey=encrypted_x25519_privkey,
            x25519_pubkey=x25519_pubkey,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def set_totp_secret(
        self,
        user_id: UUID,
        totp_secret_encrypted: bytes | None,
    ) -> VaultUser | None:
        """Set or clear `totp_secret_encrypted` (#164).

        `None` → disable TOTP. Returns updated row или None если
        vault_user не существует (caller → 404).
        """
        from datetime import UTC
        from datetime import datetime as _dt

        user = await self.get_user(user_id)
        if user is None:
            return None
        user.totp_secret_encrypted = totp_secret_encrypted
        user.updated_at = _dt.now(UTC)
        await self._session.flush()
        return user

    # -----------------------------------------------------------------
    # VaultGroup

    async def create_group(
        self,
        *,
        name: str,
        description: str | None,
        created_by: UUID,
    ) -> VaultGroup:
        group = VaultGroup(name=name, description=description, created_by=created_by)
        self._session.add(group)
        await self._session.flush()
        # Создатель — auto-owner.
        self._session.add(VaultGroupMember(group_id=group.id, user_id=created_by, role="owner"))
        await self._session.flush()
        return group

    async def list_groups_for_user(self, user_id: UUID) -> list[VaultGroup]:
        stmt = (
            select(VaultGroup)
            .join(VaultGroupMember, VaultGroupMember.group_id == VaultGroup.id)
            .where(VaultGroupMember.user_id == user_id)
            .order_by(VaultGroup.name)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def is_group_member(self, group_id: UUID, user_id: UUID) -> bool:
        stmt = select(VaultGroupMember).where(
            (VaultGroupMember.group_id == group_id) & (VaultGroupMember.user_id == user_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_group(self, group_id: UUID) -> VaultGroup | None:
        result = await self._session.execute(select(VaultGroup).where(VaultGroup.id == group_id))
        return result.scalar_one_or_none()

    async def get_group_member(
        self,
        group_id: UUID,
        user_id: UUID,
    ) -> VaultGroupMember | None:
        result = await self._session.execute(
            select(VaultGroupMember).where(
                (VaultGroupMember.group_id == group_id) & (VaultGroupMember.user_id == user_id)
            )
        )
        return result.scalar_one_or_none()

    async def list_group_members(self, group_id: UUID) -> list[VaultGroupMember]:
        result = await self._session.execute(
            select(VaultGroupMember)
            .where(VaultGroupMember.group_id == group_id)
            .order_by(VaultGroupMember.added_at)
        )
        return list(result.scalars().all())

    async def add_group_member(
        self,
        *,
        group_id: UUID,
        user_id: UUID,
        role: str = "member",
    ) -> VaultGroupMember:
        member = VaultGroupMember(group_id=group_id, user_id=user_id, role=role)
        self._session.add(member)
        await self._session.flush()
        return member

    async def remove_group_member(
        self,
        *,
        group_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Returns True если row удалена, False если её не было.

        Owner CAN'T remove themselves (defensive — иначе group остаётся
        без owner'а и becomes management-orphaned). Endpoint enforce'ит.
        """
        member = await self.get_group_member(group_id, user_id)
        if member is None:
            return False
        await self._session.delete(member)
        await self._session.flush()
        return True

    # -----------------------------------------------------------------
    # VaultSecret

    async def create_secret(
        self,
        *,
        title_ciphertext: bytes,
        category: str,
        owner_id: UUID,
        blob_ciphertext: bytes,
        wraps: list[VaultSecretWrap],
    ) -> VaultSecret:
        """Create secret + blob + wraps atomically.

        `wraps` — list of pre-constructed VaultSecretWrap, по одному
        на recipient (user или group). `secret_id` будет set по PK
        после flush.
        """
        secret = VaultSecret(
            title_ciphertext=title_ciphertext,
            category=category,
            owner_id=owner_id,
        )
        self._session.add(secret)
        await self._session.flush()  # populate secret.id

        blob = VaultSecretBlob(
            secret_id=secret.id,
            ciphertext=blob_ciphertext,
        )
        self._session.add(blob)
        for w in wraps:
            w.secret_id = secret.id
            self._session.add(w)
        await self._session.flush()
        return secret

    async def get_secret(self, secret_id: UUID) -> VaultSecret | None:
        result = await self._session.execute(select(VaultSecret).where(VaultSecret.id == secret_id))
        return result.scalar_one_or_none()

    async def get_secret_blob(self, secret_id: UUID) -> VaultSecretBlob | None:
        result = await self._session.execute(
            select(VaultSecretBlob).where(VaultSecretBlob.secret_id == secret_id)
        )
        return result.scalar_one_or_none()

    async def get_wraps_for_recipient(
        self,
        *,
        secret_id: UUID,
        user_id: UUID,
        user_group_ids: list[UUID],  # noqa: ARG002 — kept для API compat, ADR-0017
    ) -> list[VaultSecretWrap]:
        """Wraps доступные данному user (ADR-0017).

        После ADR-0017 group_id — pure lineage metadata, не authorization.
        Access определяется только через `wrap.user_id == user_id`.
        `user_group_ids` параметр сохранён для backwards-compat caller'ов
        (router calls), но игнорируется.
        """
        stmt = select(VaultSecretWrap).where(
            VaultSecretWrap.secret_id == secret_id,
            VaultSecretWrap.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def can_user_access_secret(
        self,
        *,
        secret_id: UUID,
        user_id: UUID,
        user_group_ids: list[UUID],
    ) -> bool:
        """User имеет access если есть wrap на user_id (ADR-0017).

        Group membership самой по себе НЕ даёт доступа — для доступа
        требуется personal wrap (которые добавляются client'ом при
        share-with-group flow).
        """
        wraps = await self.get_wraps_for_recipient(
            secret_id=secret_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        return len(wraps) > 0

    # -----------------------------------------------------------------
    # Sharing (ADR-0017)

    async def get_user_pubkey(self, user_id: UUID) -> bytes | None:
        """Public x25519_pubkey lookup. Returns None если user не setup'нул vault."""
        user = await self.get_user(user_id)
        return None if user is None else user.x25519_pubkey

    async def add_secret_wraps(
        self,
        *,
        secret_id: UUID,
        wraps: list[VaultSecretWrap],
    ) -> int:
        """Add wraps batch. Idempotent на (secret_id, user_id) PK:
        existing wrap'ы пропускаются (skip-on-conflict ON CONFLICT DO NOTHING).

        Returns актуально добавленное число (некоторые могли быть skipped).
        """
        from sqlalchemy.dialects.postgresql import insert

        added = 0
        for w in wraps:
            w.secret_id = secret_id
            stmt = (
                insert(VaultSecretWrap)
                .values(
                    secret_id=secret_id,
                    user_id=w.user_id,
                    group_id=w.group_id,
                    wrapped_key=w.wrapped_key,
                )
                .on_conflict_do_nothing(constraint="pk_vault_secret_wraps")
            )
            result = await self._session.execute(stmt)
            if result.rowcount and result.rowcount > 0:
                added += 1
        await self._session.flush()
        return added

    async def remove_secret_wrap(
        self,
        *,
        secret_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Remove wrap (unshare). Returns True если row была deleted."""
        from sqlalchemy import delete

        stmt = delete(VaultSecretWrap).where(
            VaultSecretWrap.secret_id == secret_id,
            VaultSecretWrap.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return bool(result.rowcount and result.rowcount > 0)

    async def update_secret_blob(
        self,
        *,
        secret_id: UUID,
        ciphertext: bytes,
        expected_version: int,
    ) -> VaultSecretBlob | None:
        """Optimistic concurrency — update только если version matches.

        Returns updated blob если version OK, None если конфликт
        (caller должен обновить view и retry).
        """
        # SELECT FOR UPDATE — lock blob row на duration транзакции.
        result = await self._session.execute(
            select(VaultSecretBlob).where(VaultSecretBlob.secret_id == secret_id).with_for_update()
        )
        blob = result.scalar_one_or_none()
        if blob is None:
            return None
        if blob.payload_version != expected_version:
            return None
        blob.ciphertext = ciphertext
        blob.payload_version = expected_version + 1
        await self._session.flush()
        return blob

    async def archive_secret(self, secret_id: UUID) -> bool:
        """Soft-delete. Audit log сохраняется (compliance trail)."""
        from datetime import UTC, datetime

        secret = await self.get_secret(secret_id)
        if secret is None or secret.archived_at is not None:
            return False
        secret.archived_at = datetime.now(UTC)
        await self._session.flush()
        return True


def get_vault_repository(
    session: AsyncSession = Depends(get_session),
) -> VaultRepository:
    return VaultRepository(session)
