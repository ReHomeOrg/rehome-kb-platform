"""AuditRepository (E4.x #102).

Single method `record(...)` — INSERT row в текущую AsyncSession, БЕЗ
commit'а. Caller commit'ит вместе с trigger'ом — это даёт at-least-once
гарантию: либо обе записи зафиксированы, либо обе rollback'нулись.

`list_records(...)` — read-side search для compliance UI (#163,
ФЗ-152 Subject Access Request).

ADR-0008 Repository pattern.
"""

from datetime import datetime
from typing import Any

from fastapi import Depends
from sqlalchemy import select
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
        # `audit_metadata` Python attribute → `metadata` DB column. Rename
        # обходит clash с `Base.metadata` (SQLAlchemy declarative reserves it).
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

    async def list_records(
        self,
        *,
        actor_sub: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        action: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLog]:
        """Filtered query для compliance UI (#163).

        Каждый фильтр — optional; combined через AND. Используются
        composite indexes (ix_audit_log_actor_created,
        ix_audit_log_resource_created) — date range scan'ы должны быть
        efficient.

        Ordering: `created_at DESC` (новейшие первые — типичный compliance
        review pattern).

        Offset pagination (вместо cursor) — для admin UI с table view
        + jump-to-page. Audit log read low-volume; cursor overkill.
        """
        stmt = select(AuditLog)
        if actor_sub is not None:
            stmt = stmt.where(AuditLog.actor_sub == actor_sub)
        if resource_type is not None:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if resource_id is not None:
            stmt = stmt.where(AuditLog.resource_id == resource_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if since is not None:
            stmt = stmt.where(AuditLog.created_at >= since)
        if until is not None:
            stmt = stmt.where(AuditLog.created_at < until)
        stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


def get_audit_repository(
    session: AsyncSession = Depends(get_session),
) -> AuditRepository:
    return AuditRepository(session)
