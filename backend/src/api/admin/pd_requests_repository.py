"""PersonalDataRequestRepository (#232) — CRUD + state machine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.api.admin.pd_requests_models import (
    ALLOWED_MANUAL_TRANSITIONS,
    TERMINAL_STATUSES,
    PersonalDataRequest,
)
from src.api.db import get_session

# ФЗ-152 §15 — 30 дней.
_DUE_DAYS = 30


class InvalidPdRequestTransitionError(Exception):
    """Caller пытается transition не из ALLOWED_MANUAL_TRANSITIONS."""


class PersonalDataRequestRepository:
    """ПДн request storage layer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_filtered(
        self,
        *,
        status: str | None = None,
        type_filter: str | None = None,
        cursor: tuple[datetime, UUID] | None = None,
        limit: int = 20,
    ) -> tuple[list[PersonalDataRequest], bool]:
        """List sorted by created_at DESC."""
        stmt = select(PersonalDataRequest)
        if status is not None:
            stmt = stmt.where(PersonalDataRequest.status == status)
        if type_filter is not None:
            stmt = stmt.where(PersonalDataRequest.type == type_filter)
        if cursor is not None:
            cursor_dt, cursor_id = cursor
            stmt = stmt.where(
                or_(
                    PersonalDataRequest.created_at < cursor_dt,
                    (PersonalDataRequest.created_at == cursor_dt)
                    & (PersonalDataRequest.id < cursor_id),
                )
            )
        stmt = stmt.order_by(
            PersonalDataRequest.created_at.desc(),
            PersonalDataRequest.id.desc(),
        ).limit(limit + 1)
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def get_by_id(self, request_id: UUID) -> PersonalDataRequest | None:
        result = await self._session.execute(
            select(PersonalDataRequest).where(PersonalDataRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        type_: str,
        subject_id: UUID,
        subject_email: str | None = None,
        subject_phone: str | None = None,
        description: str | None = None,
    ) -> PersonalDataRequest:
        """Insert new request. `due_at` = now + 30d (ФЗ-152 §15).

        API готова для wiring'а будущего ingest path (user form rehome.one).
        """
        now = datetime.now(UTC)
        req = PersonalDataRequest(
            type=type_,
            status="NEW",
            subject_id=subject_id,
            subject_email=subject_email,
            subject_phone=subject_phone,
            description=description,
            due_at=now + timedelta(days=_DUE_DAYS),
            attachments=[],
        )
        self._session.add(req)
        await self._session.flush()
        return req

    async def update(
        self,
        request: PersonalDataRequest,
        *,
        status: str | None = None,
        resolution_note: str | None = None,
        attachments: list[UUID] | None = None,
    ) -> PersonalDataRequest:
        """Partial update + state-machine guard.

        - status transition валидируется через ALLOWED_MANUAL_TRANSITIONS
          → InvalidPdRequestTransitionError если invalid.
        - Transition в terminal (COMPLETED/REJECTED) set'ит completed_at
          (если ещё None).
        """
        if status is not None and status != request.status:
            allowed = ALLOWED_MANUAL_TRANSITIONS.get(request.status, frozenset())
            if status not in allowed:
                raise InvalidPdRequestTransitionError(
                    f"Cannot transition from {request.status} to {status}"
                )
            request.status = status
            if status in TERMINAL_STATUSES and request.completed_at is None:
                request.completed_at = datetime.now(UTC)

        if resolution_note is not None:
            request.resolution_note = resolution_note

        if attachments is not None:
            # Replace (no merge) — caller passes full list.
            request.attachments = list(attachments)
            flag_modified(request, "attachments")

        await self._session.flush()
        return request

    async def mark_overdue(self) -> int:
        """Background-helper: ставит OVERDUE для NEW/IN_PROGRESS с
        due_at < now. Возвращает кол-во обновлённых rows.

        Используется планируемым cron worker'ом (backlog). Сам worker
        landit'ся отдельным PR.

        Caller commit'ит.
        """
        now = datetime.now(UTC)
        stmt = select(PersonalDataRequest).where(
            PersonalDataRequest.status.in_(("NEW", "IN_PROGRESS")),
            PersonalDataRequest.due_at < now,
        )
        result = await self._session.execute(stmt)
        rows: list[PersonalDataRequest] = list(result.scalars().all())
        for r in rows:
            r.status = "OVERDUE"
        if rows:
            await self._session.flush()
        return len(rows)


def get_pd_request_repository(
    session: AsyncSession = Depends(get_session),
) -> PersonalDataRequestRepository:
    return PersonalDataRequestRepository(session)


# Keep `Any` import alive — used by typing in future patches if needed.
_ = Any


__all__ = [
    "InvalidPdRequestTransitionError",
    "PersonalDataRequestRepository",
    "get_pd_request_repository",
]
