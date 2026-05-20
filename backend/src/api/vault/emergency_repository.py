"""VaultEmergencyUnlockLog repository (ADR-0021 A).

Storage-only. Caller orchestrates: log row + security_incident +
audit row в одной транзакции.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_session
from src.api.vault.models import EMERGENCY_REASON_CATEGORIES, VaultEmergencyUnlockLog


class VaultEmergencyRepository:
    """Storage layer для vault_emergency_unlock_log."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        *,
        user_id: UUID,
        requested_by: str,
        reason_category: str,
        reason_text: str,
        security_incident_id: UUID | None,
        rkn_notify_required: bool,
    ) -> VaultEmergencyUnlockLog:
        """INSERT log row. Caller commit'ит."""
        if reason_category not in EMERGENCY_REASON_CATEGORIES:
            raise ValueError(
                f"Invalid reason_category: {reason_category!r}. "
                f"Allowed: {EMERGENCY_REASON_CATEGORIES}"
            )
        row = VaultEmergencyUnlockLog(
            user_id=user_id,
            requested_by=requested_by,
            reason_category=reason_category,
            reason_text=reason_text,
            security_incident_id=security_incident_id,
            rkn_notify_required=rkn_notify_required,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row


def get_emergency_repository(
    session: AsyncSession = Depends(get_session),
) -> VaultEmergencyRepository:
    return VaultEmergencyRepository(session)


__all__ = ["VaultEmergencyRepository", "get_emergency_repository"]
