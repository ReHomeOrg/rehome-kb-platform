"""CollaboratorRepository — CRUD + scope-aware фильтр (ADR-0014 §3).

КРИТИЧЕСКИЙ ИНВАРИАНТ ADR-0014: каждый SELECT по `collaborators`
содержит `WHERE financial_group IN (:allowed)` — storage-level filter.

ADR-0008: Repository pattern обязателен. Router не работает с
AsyncSession напрямую.

ADR-0014 §5: Status lifecycle — в Slice 1 без transition validation.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import ColumnElement, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.api.collaborators.models import Collaborator
from src.api.db import get_session


class CollaboratorRepository:
    """CRUD + scope-aware фильтр по financial_group."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_filtered(
        self,
        allowed_groups: frozenset[str],
        *,
        type_filter: str | None = None,
        status: str | None = None,
        service_area: str | None = None,
        cursor: tuple[Any, UUID] | None = None,
        limit: int = 20,
    ) -> tuple[list[Collaborator], bool]:
        """Возвращает страницу collaborators + флаг `has_more`.

        Фильтр (всегда): `financial_group IN (:allowed_groups)` — ADR-0014 §3.
        Опциональные: type, status, service_area (ILIKE substring).

        Если `allowed_groups` пустой → `([], False)` без SQL (`IN ()` =
        false в Postgres). Защитный default из `compute_visible_groups`
        не пустой, но defensive check полезен.

        Keyset pagination: `(updated_at, id) < (cursor.u, cursor.i)`
        через row-value comparison (pattern из E2.2 / articles).
        """
        if not allowed_groups:
            return [], False

        stmt = select(Collaborator).where(Collaborator.financial_group.in_(list(allowed_groups)))
        if type_filter is not None:
            stmt = stmt.where(Collaborator.type == type_filter)
        if status is not None:
            stmt = stmt.where(Collaborator.status == status)
        if service_area is not None:
            # Substring filter — service_area — текст-описание ("Москва, ЦАО"),
            # ILIKE %area% даёт ожидаемое UX (matches любой суб-район).
            stmt = stmt.where(Collaborator.service_area.ilike(f"%{service_area}%"))
        if cursor is not None:
            cursor_updated_at, cursor_id = cursor
            stmt = stmt.where(
                tuple_(Collaborator.updated_at, Collaborator.id)
                < tuple_(literal(cursor_updated_at), literal(cursor_id))
            )

        stmt = stmt.order_by(Collaborator.updated_at.desc(), Collaborator.id.desc()).limit(
            limit + 1
        )

        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def get_by_id(
        self,
        collaborator_id: UUID,
        allowed_groups: frozenset[str],
    ) -> Collaborator | None:
        """Возвращает Collaborator по id или None если scope не видит / нет.

        404-mask (ADR-0014 §3 / ADR-0003): не различаем «нет коллаборанта»
        и «нет доступа».
        """
        if not allowed_groups:
            return None
        clauses: list[ColumnElement[bool]] = [
            Collaborator.id == collaborator_id,
            Collaborator.financial_group.in_(list(allowed_groups)),
        ]
        stmt = select(Collaborator).where(*clauses).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, collaborator: Collaborator) -> Collaborator:
        """Inserts new collaborator. Caller отвечает за `session.commit()`."""
        self._session.add(collaborator)
        await self._session.flush()
        return collaborator

    async def update_fields(
        self,
        collaborator: Collaborator,
        updates: dict[str, Any],
        *,
        jsonb_fields: tuple[str, ...] = (
            "contacts",
            "financial_terms",
            "api_integration",
            "sla",
            "counterparty_check",
        ),
    ) -> Collaborator:
        """Применяет partial update + `flag_modified` для JSONB полей.

        SQLAlchemy ORM не detects mutations внутри JSONB list/dict
        automatically — каждое JSONB поле нужно явно помечать. Pattern
        из documents.upsert_file.
        """
        for key, value in updates.items():
            setattr(collaborator, key, value)
            if key in jsonb_fields:
                flag_modified(collaborator, key)
        await self._session.flush()
        return collaborator

    async def archive(self, collaborator: Collaborator) -> Collaborator:
        """Soft delete — status → ARCHIVED. Caller commit'ит."""
        collaborator.status = "ARCHIVED"
        await self._session.flush()
        return collaborator


def get_collaborator_repository(
    session: AsyncSession = Depends(get_session),
) -> CollaboratorRepository:
    """FastAPI Depends factory."""
    return CollaboratorRepository(session)
