"""SecurityIncidentRepository (#231) — CRUD + state machine.

`create` API запланирована для wiring'а audit.security_event emitter
(#223) — backlog: wire после merges обоих PR'ов. Этот PR landит чистый
CRUD (list + get + patch).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.security_incidents_models import (
    TERMINAL_STATUSES,
    SecurityIncident,
    requires_rkn_notification,
)
from src.api.db import get_session


class InvalidIncidentTransitionError(Exception):
    """Invalid status transition (terminal → non-terminal)."""


class SecurityIncidentRepository:
    """Security incidents storage layer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_filtered(
        self,
        *,
        severity: str | None = None,
        status: str | None = None,
        cursor: tuple[datetime, UUID] | None = None,
        limit: int = 20,
    ) -> tuple[list[SecurityIncident], bool]:
        """Paginated list, sorted by detected_at DESC."""
        stmt = select(SecurityIncident)
        if severity is not None:
            stmt = stmt.where(SecurityIncident.severity == severity)
        if status is not None:
            stmt = stmt.where(SecurityIncident.status == status)
        if cursor is not None:
            cursor_dt, cursor_id = cursor
            stmt = stmt.where(
                or_(
                    SecurityIncident.detected_at < cursor_dt,
                    (SecurityIncident.detected_at == cursor_dt)
                    & (SecurityIncident.id < cursor_id),
                )
            )
        stmt = stmt.order_by(
            SecurityIncident.detected_at.desc(), SecurityIncident.id.desc()
        ).limit(limit + 1)
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def get_by_id(self, incident_id: UUID) -> SecurityIncident | None:
        result = await self._session.execute(
            select(SecurityIncident).where(SecurityIncident.id == incident_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        incident_type: str,
        severity: str,
        detected_by: str,
        affected_resources: list[dict[str, Any]] | None = None,
    ) -> SecurityIncident:
        """Insert новый incident. status default 'OPEN',
        `rkn_notification_required` derived из severity.

        Caller commit'ит.

        Used by:
        - Future wiring из `report_security_event` (#223 emitter):
          severity 'critical' → 'critical', 'warning' → 'medium',
          'info' → 'low' (mapping в caller layer).
        """
        incident = SecurityIncident(
            incident_type=incident_type,
            severity=severity,
            status="OPEN",
            detected_by=detected_by,
            affected_resources=list(affected_resources or []),
            rkn_notification_required=requires_rkn_notification(severity),
        )
        self._session.add(incident)
        await self._session.flush()
        return incident

    async def update(
        self,
        incident: SecurityIncident,
        *,
        status: str | None = None,
        resolution_note: str | None = None,
        rkn_notified_at: datetime | None = None,
    ) -> SecurityIncident:
        """Partial update + state-machine guard.

        - Terminal → non-terminal transition → InvalidIncidentTransitionError.
        - Transition в terminal status → set `resolved_at` если ещё не set.

        `resolution_note` / `rkn_notified_at` — passthrough; None = «не
        передан в payload» (PATCH exclude_unset semantic уже на router'е).
        """
        if status is not None and status != incident.status:
            if incident.status in TERMINAL_STATUSES and status not in TERMINAL_STATUSES:
                raise InvalidIncidentTransitionError(
                    f"Cannot transition from terminal status {incident.status} "
                    f"to non-terminal {status}"
                )
            incident.status = status
            if status in TERMINAL_STATUSES and incident.resolved_at is None:
                incident.resolved_at = datetime.now(UTC)
            elif status not in TERMINAL_STATUSES:
                # Re-open (INVESTIGATING ← was somehow set'нут OPEN handled
                # above). resolved_at clear не делаем — terminal→non-terminal
                # запрещён CHECK constraint'ом.
                pass

        if resolution_note is not None:
            incident.resolution_note = resolution_note
        if rkn_notified_at is not None:
            incident.rkn_notified_at = rkn_notified_at

        await self._session.flush()
        return incident


def get_security_incident_repository(
    session: AsyncSession = Depends(get_session),
) -> SecurityIncidentRepository:
    return SecurityIncidentRepository(session)


__all__ = [
    "InvalidIncidentTransitionError",
    "SecurityIncidentRepository",
    "get_security_incident_repository",
]
