"""AuditRepository (E4.x #102).

Single method `record(...)` — INSERT row в текущую AsyncSession, БЕЗ
commit'а. Caller commit'ит вместе с trigger'ом — это даёт at-least-once
гарантию: либо обе записи зафиксированы, либо обе rollback'нулись.

ADR-0008 Repository pattern.
"""

from typing import Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.audit.models import AuditLog
from src.api.db import get_session


class AuditRepository:
    """Storage layer для compliance trail."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        actor_sub: str,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        """INSERT audit row в текущую транзакцию.

        Caller отвечает за commit (в той же транзакции, что и trigger).
        Если caller rollback'нется — audit row тоже исчезнет. Это
        желательное поведение: фантомных audit-записей не должно быть.

        ФЗ-152 invariant (enforced by caller): `metadata` НЕ содержит
        content / PII (body_markdown, title, password, паспорт и т.п.) —
        только action-level state (slug, access_level, status deltas).
        """
        row = AuditLog(
            actor_sub=actor_sub,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            audit_metadata=metadata or {},
        )
        self._session.add(row)
        await self._session.flush()
        return row


def get_audit_repository(
    session: AsyncSession = Depends(get_session),
) -> AuditRepository:
    return AuditRepository(session)
