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
        user_group_ids: list[UUID],
    ) -> list[VaultSecretWrap]:
        """Wraps доступные данному user через personal или group sharing.

        Каждый recipient (user или member группы) имеет свой wrapped_key,
        зашифрованный соответствующим pubkey. Возвращаем все wraps, под
        которые user имеет ключ для разворачивания.
        """
        if user_group_ids:
            stmt = select(VaultSecretWrap).where(
                VaultSecretWrap.secret_id == secret_id,
                (VaultSecretWrap.user_id == user_id)
                | (VaultSecretWrap.group_id.in_(user_group_ids)),
            )
        else:
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
        """User имеет access если есть wrap на user_id или один из его group_id."""
        wraps = await self.get_wraps_for_recipient(
            secret_id=secret_id,
            user_id=user_id,
            user_group_ids=user_group_ids,
        )
        return len(wraps) > 0

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
