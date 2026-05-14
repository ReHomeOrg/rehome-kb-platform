"""HrEmployeeRepository — CRUD foundation (#150)."""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_session
from src.api.hr.models import HrEmployee

_CURSOR_SEP = "|"


class HrEmployeeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, employee_id: UUID) -> HrEmployee | None:
        result = await self._session.execute(select(HrEmployee).where(HrEmployee.id == employee_id))
        return result.scalar_one_or_none()

    async def list_active(
        self,
        *,
        cursor: tuple[str, str] | None = None,
        limit: int = 20,
        include_terminated: bool = False,
    ) -> tuple[list[HrEmployee], bool]:
        """Cursor-paginated list.

        Default: ACTIVE + ON_LEAVE; TERMINATED скрыты (используют
        `include_terminated=True` для HR archives).
        Archived (`archived_at IS NOT NULL`) — никогда не возвращаются.
        """
        statuses = ["ACTIVE", "ON_LEAVE"]
        if include_terminated:
            statuses.append("TERMINATED")
        stmt = (
            select(HrEmployee)
            .where(
                HrEmployee.status.in_(statuses),
                HrEmployee.archived_at.is_(None),
            )
            .order_by(HrEmployee.updated_at.desc(), HrEmployee.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            cursor_dt, cursor_id = cursor
            stmt = stmt.where(
                (HrEmployee.updated_at < cursor_dt)
                | ((HrEmployee.updated_at == cursor_dt) & (HrEmployee.id < cursor_id))
            )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def create(self, **kwargs: Any) -> HrEmployee:
        emp = HrEmployee(**kwargs)
        self._session.add(emp)
        await self._session.flush()
        return emp

    async def update(self, employee_id: UUID, *, patch: dict[str, Any]) -> HrEmployee | None:
        emp = await self.get_by_id(employee_id)
        if emp is None or emp.archived_at is not None:
            return None
        for key, value in patch.items():
            setattr(emp, key, value)
        emp.updated_at = datetime.now(UTC)
        await self._session.flush()
        return emp

    async def archive(self, employee_id: UUID) -> bool:
        """Soft-delete сотрудника. Audit log compliance: PZ §7.4 — 50 лет
        хранение трудовых документов; archive_at marker, не DROP."""
        emp = await self.get_by_id(employee_id)
        if emp is None or emp.archived_at is not None:
            return False
        emp.archived_at = datetime.now(UTC)
        emp.updated_at = datetime.now(UTC)
        await self._session.flush()
        return True


def get_hr_employee_repository(
    session: AsyncSession = Depends(get_session),
) -> HrEmployeeRepository:
    return HrEmployeeRepository(session)


def encode_cursor(updated_at_iso: str, emp_id: str) -> str:
    raw = f"{updated_at_iso}{_CURSOR_SEP}{emp_id}"
    return urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str] | None:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    parts = decoded.split(_CURSOR_SEP, 1)
    if len(parts) != 2:
        return None
    return (parts[0], parts[1])
