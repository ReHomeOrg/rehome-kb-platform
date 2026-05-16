"""PremisesCollaborator junction repository (Slice 5, ТЗ §10.6).

Управляет привязками коллаборант ↔ объект. Scope-aware visibility
наследуется от Collaborator (только D-группа для guest); junction
сам по себе не имеет access_level.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.collaborators.models import Collaborator, PremisesCollaborator
from src.api.db import get_session


class PremisesCollaboratorRepository:
    """Junction CRUD + scope-aware queries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_premises(
        self,
        premises_id: UUID,
        *,
        allowed_groups: frozenset[str],
    ) -> list[tuple[PremisesCollaborator, Collaborator]]:
        """Возвращает все привязки premises_id, фильтрованные по visible
        financial_group коллабораторов.

        Scope guard: гость видит только D-группу — junction rows к A/B/C
        коллабораторам не возвращаются. ORDER BY priority ASC, role ASC.
        """
        if not allowed_groups:
            return []

        stmt = (
            select(PremisesCollaborator, Collaborator)
            .join(Collaborator, PremisesCollaborator.collaborator_id == Collaborator.id)
            .where(PremisesCollaborator.premises_id == premises_id)
            .where(Collaborator.financial_group.in_(list(allowed_groups)))
            .order_by(PremisesCollaborator.priority.asc(), PremisesCollaborator.role.asc())
        )
        result = await self._session.execute(stmt)
        # `Row` ≠ `tuple` для mypy, поэтому tuple()-unpack — нужен явный cast.
        return [(pc, c) for pc, c in result.all()]  # noqa: C416

    async def assign(
        self,
        *,
        premises_id: UUID,
        collaborator_id: UUID,
        role: str,
        priority: int,
        notes: str | None,
        assigned_by: str,
    ) -> PremisesCollaborator | None:
        """Insert junction row. Returns None if duplicate (UQ violation).

        Caller отвечает за commit'.
        """
        pc = PremisesCollaborator(
            premises_id=premises_id,
            collaborator_id=collaborator_id,
            role=role,
            priority=priority,
            notes=notes,
            assigned_by=assigned_by,
        )
        self._session.add(pc)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            return None
        return pc

    async def remove(
        self,
        *,
        premises_id: UUID,
        collaborator_id: UUID,
        role: str | None = None,
    ) -> int:
        """Удалить привязку(и). Если `role=None` — все роли этого коллаборанта
        на этом объекте. Returns кол-во удалённых строк.
        """
        from sqlalchemy import delete

        stmt = delete(PremisesCollaborator).where(
            PremisesCollaborator.premises_id == premises_id,
            PremisesCollaborator.collaborator_id == collaborator_id,
        )
        if role is not None:
            stmt = stmt.where(PremisesCollaborator.role == role)
        result = await self._session.execute(stmt)
        return result.rowcount


def get_premises_collaborator_repository(
    session: AsyncSession = Depends(get_session),
) -> PremisesCollaboratorRepository:
    """FastAPI Depends factory."""
    return PremisesCollaboratorRepository(session)
