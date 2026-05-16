"""FastAPI router для `/api/v1/premises/{id}/collaborators/*` (Slice 5).

Endpoints:
- `GET /premises/{premises_id}/collaborators` — scope-aware list.
- `POST /premises/{premises_id}/collaborators` — assign (STAFF+).
- `DELETE /premises/{premises_id}/collaborators/{collaborator_id}` —
  remove (STAFF+, optionally by role).

Scope visibility наследуется от Collaborator: гость видит D-группу
junction rows. Premises существование сам по себе не маскируется —
если premises_id не существует, ответ — пустой list (не 404, чтобы не
leak'ить premises existence).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.audit import (
    AuditRepository,
    get_audit_repository,
)
from src.api.auth.dependency import get_current_access_levels, require_access_level
from src.api.auth.scope import AccessLevel
from src.api.collaborators.access import compute_visible_groups
from src.api.collaborators.junction_repository import (
    PremisesCollaboratorRepository,
    get_premises_collaborator_repository,
)
from src.api.collaborators.schemas import (
    CollaboratorPublic,
    PremisesCollaboratorAssignment,
    PremisesCollaboratorRow,
    PremisesCollaboratorsListResponse,
)
from src.api.db import get_session

# Используем отдельный prefix — `/premises/{premises_id}/collaborators`
# (не относится к /collaborators namespace).
router = APIRouter(
    prefix="/premises/{premises_id}/collaborators", tags=["Collaborators"]
)


# Audit actions for junction (определены здесь чтобы не раздувать
# audit/actions.py — junction events local к Slice 5).
ACTION_PREMISES_COLLABORATOR_ASSIGNED = "premises.collaborator.assigned"
ACTION_PREMISES_COLLABORATOR_UNASSIGNED = "premises.collaborator.unassigned"
RESOURCE_PREMISES_COLLABORATOR = "premises_collaborator"


@router.get(
    "",
    response_model=PremisesCollaboratorsListResponse,
    summary="Коллаборанты, обслуживающие объект",
)
async def list_premises_collaborators(
    premises_id: UUID = Path(...),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: PremisesCollaboratorRepository = Depends(get_premises_collaborator_repository),
) -> PremisesCollaboratorsListResponse:
    """`GET /api/v1/premises/{premises_id}/collaborators` (ТЗ §10.7).

    Scope-aware: guest/LOGGED видит только D-группу junction rows.
    Ordering: priority ASC, role ASC (emergency-сервисы первыми).
    """
    allowed_groups = compute_visible_groups(access_levels)
    rows = await repo.list_for_premises(premises_id, allowed_groups=allowed_groups)
    return PremisesCollaboratorsListResponse(
        data=[
            PremisesCollaboratorRow(
                id=pc.id,
                collaborator_id=pc.collaborator_id,
                role=pc.role,
                priority=pc.priority,
                notes=pc.notes,
                assigned_at=pc.assigned_at,
                assigned_by=pc.assigned_by,
                collaborator=CollaboratorPublic.model_validate(c),
            )
            for pc, c in rows
        ]
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PremisesCollaboratorRow,
    summary="Назначить коллаборанта на объект (STAFF+)",
    responses={
        201: {"description": "Назначен"},
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Premises или collaborator не существует"},
        409: {"description": "Уже назначен с этой ролью"},
    },
)
async def assign_collaborator_to_premises(
    payload: PremisesCollaboratorAssignment,
    premises_id: UUID = Path(...),
    _claims: dict[str, Any] = Depends(require_access_level(AccessLevel.STAFF)),
    repo: PremisesCollaboratorRepository = Depends(get_premises_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
) -> PremisesCollaboratorRow:
    """`POST /api/v1/premises/{premises_id}/collaborators` (STAFF+).

    404 — если premises/collaborator не существует (FK violation).
    409 — duplicate triplet (premises_id, collaborator_id, role).
    """
    pc = await repo.assign(
        premises_id=premises_id,
        collaborator_id=payload.collaborator_id,
        role=payload.role,
        priority=payload.priority,
        notes=payload.notes,
        assigned_by="staff",
    )
    if pc is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Collaborator {payload.collaborator_id} уже назначен на "
                f"premises {premises_id} с ролью '{payload.role}'"
            ),
        )

    # Получить collaborator для response (через scope-aware list).
    allowed_groups = compute_visible_groups(access_levels)
    rows = await repo.list_for_premises(premises_id, allowed_groups=allowed_groups)
    pair = next((r for r in rows if r[0].id == pc.id), None)
    if pair is None:
        # Should not happen — staff видит все groups.
        raise HTTPException(status_code=500, detail="Junction row not visible after insert")
    _, collaborator = pair

    await audit.record(
        actor_sub="staff",
        action=ACTION_PREMISES_COLLABORATOR_ASSIGNED,
        resource_type=RESOURCE_PREMISES_COLLABORATOR,
        resource_id=str(pc.id),
        metadata={
            "premises_id": str(premises_id),
            "collaborator_id": str(payload.collaborator_id),
            "role": payload.role,
            "priority": payload.priority,
        },
    )
    await session.commit()
    return PremisesCollaboratorRow(
        id=pc.id,
        collaborator_id=pc.collaborator_id,
        role=pc.role,
        priority=pc.priority,
        notes=pc.notes,
        assigned_at=pc.assigned_at,
        assigned_by=pc.assigned_by,
        collaborator=CollaboratorPublic.model_validate(collaborator),
    )


@router.delete(
    "/{collaborator_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отвязать коллаборанта от объекта (STAFF+)",
    responses={
        204: {"description": "Удалено (one or more rows)"},
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Связь не найдена"},
    },
)
async def unassign_collaborator_from_premises(
    premises_id: UUID = Path(...),
    collaborator_id: UUID = Path(...),
    role: str | None = Query(
        default=None,
        max_length=50,
        description="Если указан — удалить только эту роль. Иначе — все роли.",
    ),
    _claims: dict[str, Any] = Depends(require_access_level(AccessLevel.STAFF)),
    repo: PremisesCollaboratorRepository = Depends(get_premises_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> None:
    """`DELETE /api/v1/premises/{premises_id}/collaborators/{collaborator_id}`.

    Hard delete junction rows. Audit log сохраняется (compliance trail).
    """
    deleted = await repo.remove(
        premises_id=premises_id,
        collaborator_id=collaborator_id,
        role=role,
    )
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Assignment not found")

    await audit.record(
        actor_sub="staff",
        action=ACTION_PREMISES_COLLABORATOR_UNASSIGNED,
        resource_type=RESOURCE_PREMISES_COLLABORATOR,
        resource_id=None,
        metadata={
            "premises_id": str(premises_id),
            "collaborator_id": str(collaborator_id),
            "role": role,
            "rows_deleted": deleted,
        },
    )
    await session.commit()
