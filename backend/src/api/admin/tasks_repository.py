"""AdminTaskRepository (#238). CRUD над admin_tasks table.

Storage-only. Execution logic (что собственно делает reindex / export)
живёт в router'ах, repo только persist'ит task lifecycle.

ADR-0008 Repository pattern.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.tasks_models import (
    TASK_STATUSES,
    TASK_TYPES,
    TERMINAL_TASK_STATUSES,
    AdminTask,
)
from src.api.db import get_session


class AdminTaskRepository:
    """admin_tasks storage layer."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        type_: str,
        actor_sub: str,
        params: dict[str, Any] | None = None,
    ) -> AdminTask:
        """INSERT с status=PENDING. Caller responsible за переход в RUNNING/COMPLETED."""
        if type_ not in TASK_TYPES:
            raise ValueError(f"Unknown task type: {type_}")
        row = AdminTask(
            type=type_,
            actor_sub=actor_sub,
            params=params or {},
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def mark_running(self, task_id: UUID) -> AdminTask:
        row = await self._get_or_raise(task_id)
        row.status = "RUNNING"
        await self._session.flush()
        return row

    async def mark_completed(
        self,
        task_id: UUID,
        *,
        result_url: str | None = None,
    ) -> AdminTask:
        row = await self._get_or_raise(task_id)
        row.status = "COMPLETED"
        row.progress_percent = 100
        row.result_url = result_url
        row.completed_at = datetime.now(UTC)
        await self._session.flush()
        return row

    async def mark_failed(self, task_id: UUID, *, error: str) -> AdminTask:
        row = await self._get_or_raise(task_id)
        row.status = "FAILED"
        row.error = error
        row.completed_at = datetime.now(UTC)
        await self._session.flush()
        return row

    async def get(self, task_id: UUID) -> AdminTask | None:
        return await self._session.get(AdminTask, task_id)

    async def _get_or_raise(self, task_id: UUID) -> AdminTask:
        row = await self.get(task_id)
        if row is None:
            raise LookupError(f"admin_task {task_id} not found")
        if row.status in TERMINAL_TASK_STATUSES:
            # Idempotency guard — нельзя двинуть terminal task.
            raise ValueError(f"admin_task {task_id} already in terminal status {row.status}")
        return row

    async def list_recent(
        self,
        *,
        type_: str | None = None,
        statuses: tuple[str, ...] | None = None,
        limit: int = 50,
    ) -> list[AdminTask]:
        """Admin listing — DESC по created_at."""
        if type_ and type_ not in TASK_TYPES:
            raise ValueError(f"Unknown task type: {type_}")
        if statuses:
            unknown = set(statuses) - set(TASK_STATUSES)
            if unknown:
                raise ValueError(f"Unknown task statuses: {unknown}")
        stmt = select(AdminTask).order_by(AdminTask.created_at.desc()).limit(limit)
        if type_:
            stmt = stmt.where(AdminTask.type == type_)
        if statuses:
            stmt = stmt.where(AdminTask.status.in_(statuses))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


async def get_admin_task_repository(
    session: AsyncSession = Depends(get_session),
) -> AdminTaskRepository:
    return AdminTaskRepository(session)


__all__ = ["AdminTaskRepository", "get_admin_task_repository"]
