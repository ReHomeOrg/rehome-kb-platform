"""VaultFIDO2Repository — CRUD над vault_fido2_credentials (ADR-0022 A).

Storage-only. Caller (router / service) owns commit.

Cap на multiple keys per user (MAX_KEYS_PER_USER = 5) enforced в `create`
— anti-abuse + UX clarity (primary + 4 backups).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from fastapi import Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_session
from src.api.vault.models import VaultFIDO2Credential

# Max registered FIDO2 keys per user (ADR-0022 §approve-defaults).
MAX_KEYS_PER_USER: Final = 5


class VaultFIDO2CapacityError(ValueError):
    """Raised когда user уже имеет MAX_KEYS_PER_USER registered."""


class VaultFIDO2Repository:
    """Storage layer для vault_fido2_credentials."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_user(self, user_id: UUID) -> list[VaultFIDO2Credential]:
        """Returns user's registered credentials, ascending by created_at."""
        stmt = (
            select(VaultFIDO2Credential)
            .where(VaultFIDO2Credential.user_id == user_id)
            .order_by(VaultFIDO2Credential.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_user(self, user_id: UUID) -> int:
        """Returns number of credentials for cap-check."""
        # Cheap SELECT count(*) — fine на ≤5 rows per user.
        rows = await self.list_by_user(user_id)
        return len(rows)

    async def get_by_credential_id(self, credential_id: bytes) -> VaultFIDO2Credential | None:
        """Lookup by WebAuthn credentialID (assertion verification)."""
        stmt = select(VaultFIDO2Credential).where(
            VaultFIDO2Credential.credential_id == credential_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, credential_pk: UUID, *, user_id: UUID) -> VaultFIDO2Credential | None:
        """Lookup by surrogate PK, scoped к user_id (anti-tamper)."""
        stmt = select(VaultFIDO2Credential).where(
            VaultFIDO2Credential.id == credential_pk,
            VaultFIDO2Credential.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: UUID,
        credential_id: bytes,
        public_key: bytes,
        transports: list[str],
        aaguid: bytes | None = None,
        nickname: str | None = None,
        sign_count: int = 0,
    ) -> VaultFIDO2Credential:
        """INSERT credential. Enforces MAX_KEYS_PER_USER cap.

        Raises VaultFIDO2CapacityError если user уже на cap'е.
        Caller responsible за `await session.commit()`.
        """
        existing = await self.count_by_user(user_id)
        if existing >= MAX_KEYS_PER_USER:
            raise VaultFIDO2CapacityError(
                f"Max {MAX_KEYS_PER_USER} FIDO2 keys per user; revoke an existing key first."
            )

        row = VaultFIDO2Credential(
            user_id=user_id,
            credential_id=credential_id,
            public_key=public_key,
            transports=list(transports),
            aaguid=aaguid,
            nickname=nickname,
            sign_count=sign_count,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def update_sign_count(
        self,
        credential_pk: UUID,
        new_sign_count: int,
    ) -> None:
        """Increment sign_count + bump last_used_at after successful assert.

        Caller обязан validate'ить что `new_sign_count > current` ДО
        вызова (replay detection — фиксируется на router-уровне как
        security_incident).
        """
        row = await self._session.get(VaultFIDO2Credential, credential_pk)
        if row is None:
            return
        row.sign_count = new_sign_count
        row.last_used_at = datetime.now(UTC)
        await self._session.flush()

    async def delete_by_id(self, credential_pk: UUID, *, user_id: UUID) -> bool:
        """DELETE credential scoped к user_id. Returns True если deleted."""
        stmt = delete(VaultFIDO2Credential).where(
            VaultFIDO2Credential.id == credential_pk,
            VaultFIDO2Credential.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        return (result.rowcount or 0) > 0


def get_fido2_repository(
    session: AsyncSession = Depends(get_session),
) -> VaultFIDO2Repository:
    return VaultFIDO2Repository(session)


__all__ = [
    "MAX_KEYS_PER_USER",
    "VaultFIDO2CapacityError",
    "VaultFIDO2Repository",
    "get_fido2_repository",
]
