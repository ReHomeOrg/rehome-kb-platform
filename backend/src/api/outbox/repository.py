"""OutboxRepository — enqueue + fetch_unflushed + mark_flushed (ADR-0026).

`enqueue` принимает external session (caller commit'ит в same transaction
что и business write). `fetch_unflushed` + `mark_flushed` + `record_failure`
— drainer-side.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db import get_session
from src.api.outbox.models import OutboxRow

# Hard cap на last_error длину — anti-DoS если exception traceback huge.
_LAST_ERROR_MAX_LENGTH = 2000


class OutboxRepository:
    """Storage layer для outbox table (#356, ADR-0026)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> OutboxRow:
        """Insert outbox row в текущую сессию. Caller commit'ит вместе
        с business write (atomic).

        Не делает explicit `flush` — DDL constraints проверятся на
        session commit. Returns ORM row для caller'а если нужен id.
        """
        row = OutboxRow(event_type=event_type, payload=payload)
        self._session.add(row)
        return row

    async def fetch_unflushed(self, *, limit: int) -> list[OutboxRow]:
        """Drainer-side: returns unflushed rows (oldest first).

        FOR UPDATE SKIP LOCKED — позволяет concurrent drainer instances
        не конкурировать; backlog (single-instance MVP OK).
        """
        stmt = (
            select(OutboxRow)
            .where(OutboxRow.flushed_at.is_(None))
            .order_by(OutboxRow.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_flushed(self, row_id: UUID) -> None:
        """Set flushed_at=now() — drainer вызывает после successful fan-out."""
        stmt = (
            update(OutboxRow)
            .where(OutboxRow.id == row_id)
            .values(flushed_at=datetime.now(UTC))
        )
        await self._session.execute(stmt)

    async def record_failure(
        self,
        row_id: UUID,
        *,
        error: str,
    ) -> None:
        """Bump retries counter + store truncated error. Drainer вызывает
        при exception во время fan-out — row остаётся unflushed для retry
        на next iteration."""
        truncated = error[:_LAST_ERROR_MAX_LENGTH]
        stmt = (
            update(OutboxRow)
            .where(OutboxRow.id == row_id)
            .values(
                retries=OutboxRow.retries + 1,
                last_error=truncated,
            )
        )
        await self._session.execute(stmt)


def get_outbox_repository(
    session: AsyncSession = Depends(get_session),
) -> OutboxRepository:
    return OutboxRepository(session)


__all__ = ["OutboxRepository", "get_outbox_repository"]
