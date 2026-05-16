"""FastAPI router для `/api/v1/collaborators/*` (ADR-0014, ТЗ §10).

Endpoints (Slice 1):
- `GET /collaborators` — list с фильтрами (scope-aware visibility).
- `GET /collaborators/{id}` — detail (3 schema variants per scope).
- `POST /collaborators` — create (STAFF only). D-группа auto-ACTIVE.
- `PATCH /collaborators/{id}` — partial update (STAFF only).
- `DELETE /collaborators/{id}` — archive soft (STAFF only).

Backlog (отдельные slices):
- `/activate` + `/suspend` — Slice 2 (transition validation).
- `/onboarding` + `/portal-access` — Slice 3.
- `/metrics`, `PremisesCollaborator`, `reviews`, `service_orders` — Slice 4+.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.cursor import decode_cursor, encode_cursor
from src.api.audit import (
    ACTION_COLLABORATOR_ACTIVATED,
    ACTION_COLLABORATOR_ARCHIVED,
    ACTION_COLLABORATOR_CREATED,
    ACTION_COLLABORATOR_SUSPENDED,
    ACTION_COLLABORATOR_UPDATED,
    RESOURCE_COLLABORATOR,
    AuditRepository,
    get_audit_repository,
)
from src.api.auth.dependency import get_current_access_levels, require_access_level
from src.api.auth.scope import AccessLevel
from src.api.collaborators.access import compute_visible_groups
from src.api.collaborators.lifecycle import validate_activation, validate_suspension
from src.api.collaborators.models import Collaborator
from src.api.collaborators.repository import (
    CollaboratorRepository,
    get_collaborator_repository,
)
from src.api.collaborators.schemas import (
    CollaboratorAdmin,
    CollaboratorCreate,
    CollaboratorInternal,
    CollaboratorPatch,
    CollaboratorPublic,
    CollaboratorsListResponse,
    PaginationInfo,
    SuspendRequest,
)
from src.api.db import get_session

router = APIRouter(prefix="/collaborators", tags=["Collaborators"])

LIMIT_MIN = 1
LIMIT_MAX = 100
LIMIT_DEFAULT = 20

CollaboratorTypePath = Literal[
    "management_company",
    "emergency_service",
    "repair_handyman",
    "cleaning",
    "moving",
    "key_delivery",
    "insurance",
    "payment_partner",
    "kyc_provider",
    "edo_provider",
    "sms_voice",
    "it_infrastructure",
    "legal_consultant",
    "other",
]
StatusPath = Literal["DRAFT", "PENDING_REVIEW", "ACTIVE", "SUSPENDED", "ARCHIVED"]


def _has_staff_scope(access_levels: frozenset[AccessLevel]) -> bool:
    """Helper: scope-set содержит STAFF/LEGAL/HR — может видеть internal-данные."""
    return bool(access_levels & {AccessLevel.STAFF, AccessLevel.LEGAL, AccessLevel.HR_RESTRICTED})


def _serialize_for_scope(
    c: Collaborator, access_levels: frozenset[AccessLevel]
) -> CollaboratorPublic | CollaboratorInternal | CollaboratorAdmin:
    """Выбирает Pydantic variant per scope (ADR-0014 §7)."""
    # staff_admin (heuristic: STAFF + LEGAL вместе — admin-set) видит audit_log.
    if AccessLevel.STAFF in access_levels and AccessLevel.LEGAL in access_levels:
        return CollaboratorAdmin.model_validate(c)
    if _has_staff_scope(access_levels):
        return CollaboratorInternal.model_validate(c)
    return CollaboratorPublic.model_validate(c)


@router.get(
    "",
    response_model=CollaboratorsListResponse,
    summary="Список коллаборантов",
)
async def list_collaborators(
    type_filter: CollaboratorTypePath | None = Query(default=None, alias="type"),
    status_filter: StatusPath | None = Query(default=None, alias="status"),
    service_area: str | None = Query(default=None, max_length=200),
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=LIMIT_DEFAULT, ge=LIMIT_MIN, le=LIMIT_MAX),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
) -> CollaboratorsListResponse:
    """`GET /api/v1/collaborators` — список с фильтрами + scope-aware visibility.

    ADR-0014 §3: scope маппится в visible financial_groups через
    `compute_visible_groups`. Outside-scope коллаборанты физически
    не возвращаются (фильтр на SQL-уровне).

    Response items — `CollaboratorPublic` для guest/LOGGED (D only) или
    `CollaboratorInternal` для STAFF+.
    """
    allowed_groups = compute_visible_groups(access_levels)
    cursor_pair = decode_cursor(cursor) if cursor else None

    rows, has_more = await repo.list_filtered(
        allowed_groups,
        type_filter=type_filter,
        status=status_filter,
        service_area=service_area,
        cursor=cursor_pair,
        limit=limit,
    )

    cursor_next: str | None = None
    if has_more and rows:
        last = rows[-1]
        cursor_next = encode_cursor(last.updated_at, last.id)

    return CollaboratorsListResponse(
        data=[_serialize_for_scope(c, access_levels) for c in rows],
        pagination=PaginationInfo(cursor_next=cursor_next, has_more=has_more),
    )


@router.get(
    "/{collaborator_id}",
    summary="Карточка коллаборанта",
    responses={404: {"description": "Не найден или scope не видит (anti-enum mask)"}},
)
async def get_collaborator(
    collaborator_id: UUID = Path(...),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
) -> CollaboratorPublic | CollaboratorInternal | CollaboratorAdmin:
    """`GET /api/v1/collaborators/{id}` — detail per scope.

    404 (mask) если scope не видит ИЛИ id не существует. ADR-0014 §3.
    """
    allowed_groups = compute_visible_groups(access_levels)
    c = await repo.get_by_id(collaborator_id, allowed_groups)
    if c is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")
    return _serialize_for_scope(c, access_levels)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Создать коллаборанта (STAFF+)",
    responses={
        201: {"description": "Создан в DRAFT (или ACTIVE для D-группы автоматически)"},
        403: {"description": "Требуется STAFF scope"},
        422: {"description": "Невалидный type / financial_group invariant"},
    },
)
async def create_collaborator(
    payload: CollaboratorCreate,
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    _claims: dict[str, Any] = Depends(require_access_level(AccessLevel.STAFF)),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
) -> CollaboratorPublic | CollaboratorInternal | CollaboratorAdmin:
    """`POST /api/v1/collaborators` — STAFF-only.

    D-группа (management_company, emergency_service) auto-ACTIVE
    (ТЗ §3.10.1). Остальные — статус из payload (по умолчанию DRAFT).
    """
    # D-группа → auto-ACTIVE (ТЗ §3.10.1). financial_group уже derived
    # в CollaboratorCreate.resolve_financial_group.
    effective_status = payload.status
    if payload.financial_group == "D" and payload.status == "DRAFT":
        effective_status = "ACTIVE"

    c = Collaborator(
        name=payload.name,
        brand_name=payload.brand_name,
        type=payload.type,
        financial_group=payload.financial_group,
        status=effective_status,
        legal_entity_type=payload.legal_entity_type,
        inn=payload.inn,
        ogrn=payload.ogrn,
        kpp=payload.kpp,
        service_area=payload.service_area,
        working_hours=payload.working_hours,
        website=payload.website,
        responsible_internal=payload.responsible_internal,
        contract_document_id=payload.contract_document_id,
        fallback_collaborator_id=payload.fallback_collaborator_id,
        contacts=[entry.model_dump() for entry in payload.contacts],
        financial_terms=payload.financial_terms,
        api_integration=payload.api_integration,
        sla=payload.sla,
        counterparty_check=payload.counterparty_check,
    )
    await repo.create(c)

    actor_sub = "staff"  # TODO Slice 2: extract from JWT properly
    await audit.record(
        actor_sub=actor_sub,
        action=ACTION_COLLABORATOR_CREATED,
        resource_type=RESOURCE_COLLABORATOR,
        resource_id=str(c.id),
        metadata={
            "type": c.type,
            "financial_group": c.financial_group,
            "status": c.status,
        },
    )
    await session.commit()

    # STAFF+ always gets Internal/Admin variant (inherits Public).
    return _serialize_for_scope(c, access_levels)


@router.patch(
    "/{collaborator_id}",
    summary="Обновить коллаборанта (STAFF+)",
    responses={
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Не найден"},
        422: {"description": "Невалидный type/group invariant"},
    },
)
async def patch_collaborator(
    payload: CollaboratorPatch,
    collaborator_id: UUID = Path(...),
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
) -> CollaboratorPublic | CollaboratorInternal | CollaboratorAdmin:
    """`PATCH /api/v1/collaborators/{id}` — partial update, STAFF+ only."""
    allowed_groups = compute_visible_groups(access_levels)
    c = await repo.get_by_id(collaborator_id, allowed_groups)
    if c is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    # Преобразуем payload в plain dict, исключая None (PATCH semantics).
    updates = payload.model_dump(exclude_unset=True)

    await repo.update_fields(c, updates)

    await audit.record(
        actor_sub="staff",
        action=ACTION_COLLABORATOR_UPDATED,
        resource_type=RESOURCE_COLLABORATOR,
        resource_id=str(c.id),
        metadata={"updated_fields": sorted(updates.keys())},
    )
    await session.commit()

    return _serialize_for_scope(c, access_levels)


@router.delete(
    "/{collaborator_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Архивировать коллаборанта (soft delete, STAFF+)",
    responses={
        204: {"description": "Архивирован (status=ARCHIVED)"},
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Не найден"},
    },
)
async def archive_collaborator(
    collaborator_id: UUID = Path(...),
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
) -> None:
    """`DELETE /api/v1/collaborators/{id}` — soft delete → ARCHIVED."""
    allowed_groups = compute_visible_groups(access_levels)
    c = await repo.get_by_id(collaborator_id, allowed_groups)
    if c is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    previous_status = c.status
    await repo.archive(c)

    await audit.record(
        actor_sub="staff",
        action=ACTION_COLLABORATOR_ARCHIVED,
        resource_type=RESOURCE_COLLABORATOR,
        resource_id=str(c.id),
        metadata={"previous_status": previous_status},
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Lifecycle (Slice 2, ADR-0014 §5, ТЗ §3.10.2)


@router.post(
    "/{collaborator_id}/activate",
    summary="Активация коллаборанта (STAFF+)",
    responses={
        200: {"description": "Активирован (status=ACTIVE)"},
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Не найден"},
        422: {"description": "Не выполнены invariants активации"},
    },
)
async def activate_collaborator(
    collaborator_id: UUID = Path(...),
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
) -> CollaboratorPublic | CollaboratorInternal | CollaboratorAdmin:
    """`POST /api/v1/collaborators/{id}/activate` (ТЗ §3.10.2).

    Транзишн: DRAFT / PENDING_REVIEW / SUSPENDED → ACTIVE.

    Invariants (ADR-0014 §5):
    - `counterparty_check.result = "CLEAN"` (для групп A/B/C)
    - `contract_document_id != null` (для A/B/C)
    - `responsible_internal != null` (для всех, кроме D)

    Нарушения → 422 со списком violations в `detail`.
    """
    allowed_groups = compute_visible_groups(access_levels)
    c = await repo.get_by_id(collaborator_id, allowed_groups)
    if c is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    violations = validate_activation(
        current_status=c.status,
        financial_group=c.financial_group,
        counterparty_check=c.counterparty_check,
        contract_document_id=c.contract_document_id,
        responsible_internal=c.responsible_internal,
    )
    if violations:
        raise HTTPException(
            status_code=422,
            detail={
                "title": "Activation invariants not satisfied",
                "violations": [v.as_dict() for v in violations],
            },
        )

    previous_status = c.status
    await repo.update_fields(c, {"status": "ACTIVE"})

    await audit.record(
        actor_sub="staff",
        action=ACTION_COLLABORATOR_ACTIVATED,
        resource_type=RESOURCE_COLLABORATOR,
        resource_id=str(c.id),
        metadata={"previous_status": previous_status},
    )
    await session.commit()
    return _serialize_for_scope(c, access_levels)


@router.post(
    "/{collaborator_id}/suspend",
    summary="Приостановка коллаборанта (STAFF+)",
    responses={
        200: {"description": "Приостановлен (status=SUSPENDED)"},
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Не найден"},
        422: {"description": "Невалидный transition (только из ACTIVE)"},
    },
)
async def suspend_collaborator(
    payload: SuspendRequest,
    collaborator_id: UUID = Path(...),
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
) -> CollaboratorPublic | CollaboratorInternal | CollaboratorAdmin:
    """`POST /api/v1/collaborators/{id}/suspend` (ТЗ §3.10.2).

    Транзишн: ACTIVE → SUSPENDED. Требует `reason` в body
    (свободный текст для compliance trail).
    """
    allowed_groups = compute_visible_groups(access_levels)
    c = await repo.get_by_id(collaborator_id, allowed_groups)
    if c is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    violations = validate_suspension(c.status)
    if violations:
        raise HTTPException(
            status_code=422,
            detail={
                "title": "Suspend transition not allowed",
                "violations": [v.as_dict() for v in violations],
            },
        )

    previous_status = c.status
    await repo.update_fields(c, {"status": "SUSPENDED"})

    await audit.record(
        actor_sub="staff",
        action=ACTION_COLLABORATOR_SUSPENDED,
        resource_type=RESOURCE_COLLABORATOR,
        resource_id=str(c.id),
        metadata={
            "previous_status": previous_status,
            "reason": payload.reason,
            "until": payload.until,
        },
    )
    await session.commit()
    return _serialize_for_scope(c, access_levels)
