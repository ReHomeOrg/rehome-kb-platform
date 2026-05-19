"""KbUserRepository (#230) — CRUD + cursor pagination.

Filters: role / status. Ordering: (updated_at DESC, id DESC) — stable
keyset cursor.

Email duplicates → IntegrityError (UQ on `lower(email)`); router конвертит в 409.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.api.admin.users_models import KbUser
from src.api.db import get_session


class KbUserRepository:
    """KB user storage layer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_filtered(
        self,
        *,
        role: str | None = None,
        status: str | None = None,
        cursor: tuple[datetime, UUID] | None = None,
        limit: int = 20,
    ) -> tuple[list[KbUser], bool]:
        """Paginated list. `cursor` — (updated_at, id) для keyset seek.

        Returns `(rows, has_more)` через `+1-fetch overshoot` pattern.
        """
        stmt = select(KbUser)
        if role is not None:
            stmt = stmt.where(KbUser.role == role)
        if status is not None:
            stmt = stmt.where(KbUser.status == status)
        if cursor is not None:
            cursor_dt, cursor_id = cursor
            stmt = stmt.where(
                or_(
                    KbUser.updated_at < cursor_dt,
                    (KbUser.updated_at == cursor_dt) & (KbUser.id < cursor_id),
                )
            )
        stmt = stmt.order_by(KbUser.updated_at.desc(), KbUser.id.desc()).limit(limit + 1)
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def get_by_id(self, user_id: UUID) -> KbUser | None:
        result = await self._session.execute(select(KbUser).where(KbUser.id == user_id))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        email: str,
        full_name: str,
        role: str,
        permissions: list[str],
    ) -> KbUser:
        """Insert новый row. Email UQ violation → IntegrityError (router → 409).

        Caller commit'ит.
        """
        user = KbUser(
            email=email,
            full_name=full_name,
            role=role,
            permissions=list(permissions),
            status="ACTIVE",
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def update_fields(self, user: KbUser, updates: dict[str, Any]) -> KbUser:
        """In-place update. `permissions` — JSONB requires flag_modified
        для proper change-tracking SQLAlchemy.

        Caller commit'ит.
        """
        for key, value in updates.items():
            setattr(user, key, value)
        if "permissions" in updates:
            flag_modified(user, "permissions")
        await self._session.flush()
        return user

    async def deactivate(self, user: KbUser) -> KbUser:
        """Soft-delete: status → ARCHIVED. Идемпотентно (повторный →
        same state, без изменения timestamp'а).
        """
        if user.status != "ARCHIVED":
            user.status = "ARCHIVED"
            await self._session.flush()
        return user


def get_kb_user_repository(
    session: AsyncSession = Depends(get_session),
) -> KbUserRepository:
    return KbUserRepository(session)


__all__ = ["KbUserRepository", "get_kb_user_repository"]
