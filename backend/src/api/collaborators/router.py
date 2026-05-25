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

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.cursor import decode_cursor, encode_cursor
from src.api.audit import (
    ACTION_COLLABORATOR_ACTIVATED,
    ACTION_COLLABORATOR_ARCHIVED,
    ACTION_COLLABORATOR_CREATED,
    ACTION_COLLABORATOR_ONBOARDED,
    ACTION_COLLABORATOR_PORTAL_ACCESS_CHANGED,
    ACTION_COLLABORATOR_SUSPENDED,
    ACTION_COLLABORATOR_UPDATED,
    RESOURCE_COLLABORATOR,
    AuditRepository,
    get_audit_repository,
)
from src.api.auth.dependency import (
    get_current_access_levels,
    require_access_level,
    require_authenticated,
)
from src.api.auth.scope import AccessLevel
from src.api.collaborators.access import compute_visible_groups, derive_financial_group
from src.api.collaborators.lifecycle import validate_activation, validate_suspension
from src.api.collaborators.models import Collaborator
from src.api.collaborators.ratelimit import enforce_onboarding_rate_limit
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
    OnboardingRequest,
    OnboardingResponse,
    PaginationInfo,
    PortalAccessChangeRequest,
    SuspendRequest,
)
from src.api.db import get_session
from src.api.idempotency import IdempotencyResult, process_idempotency_key
from src.api.webhooks.dispatcher import (
    WebhookEventDispatcher,
    get_webhook_event_dispatcher,
)
from src.api.webhooks.events import WebhookEvent

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


async def _dispatch_lifecycle_event(
    dispatcher: WebhookEventDispatcher,
    *,
    event: WebhookEvent,
    collaborator: Collaborator,
    extras: dict[str, Any] | None = None,
) -> None:
    """Fire collaborator.* webhook event (#225, ТЗ §5.1).

    Минимальный payload — `id` + `type` + `financial_group` + `status` +
    `updated_at`. Имена / контакты / ИНН — НЕ в payload (subscriber'ы
    могут быть external; ФЗ-152 invariant: ПДн только в STAFF-scope read).

    Errors swallow'аются — webhook dispatch не должен fail'ить
    business operation (audit log уже записан в той же транзакции).
    """
    payload: dict[str, Any] = {
        "id": str(collaborator.id),
        "type": collaborator.type,
        "financial_group": collaborator.financial_group,
        "status": collaborator.status,
        "updated_at": collaborator.updated_at.isoformat(),
    }
    if extras:
        payload.update(extras)
    await dispatcher.dispatch(event_type=event.value, payload=payload)


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
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
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

    actor_sub = str(claims.get("sub", "unknown"))
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

    # #225 / ТЗ §5.1: fire `collaborator.created` webhook event.
    await _dispatch_lifecycle_event(
        webhook_dispatcher, event=WebhookEvent.COLLABORATOR_CREATED, collaborator=c
    )

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
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
) -> Any:
    """`PATCH /api/v1/collaborators/{id}` — partial update, STAFF+ only.

    Idempotency-Key (UUID header, ADR-0025): replay cached response без
    duplicate audit row.
    """
    if idempotency.replay is not None:
        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    allowed_groups = compute_visible_groups(access_levels)
    c = await repo.get_by_id(collaborator_id, allowed_groups)
    if c is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    # Преобразуем payload в plain dict, исключая None (PATCH semantics).
    updates = payload.model_dump(exclude_unset=True)

    await repo.update_fields(c, updates)

    await audit.record(
        actor_sub=str(claims.get("sub", "unknown")),
        action=ACTION_COLLABORATOR_UPDATED,
        resource_type=RESOURCE_COLLABORATOR,
        resource_id=str(c.id),
        metadata={"updated_fields": sorted(updates.keys())},
    )
    await session.commit()

    body = _serialize_for_scope(c, access_levels).model_dump(mode="json")
    await idempotency.save(status_code=200, body=body)
    return JSONResponse(status_code=200, content=body)


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
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
) -> None:
    """`DELETE /api/v1/collaborators/{id}` — soft delete → ARCHIVED."""
    allowed_groups = compute_visible_groups(access_levels)
    c = await repo.get_by_id(collaborator_id, allowed_groups)
    if c is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    previous_status = c.status
    await repo.archive(c)

    await audit.record(
        actor_sub=str(claims.get("sub", "unknown")),
        action=ACTION_COLLABORATOR_ARCHIVED,
        resource_type=RESOURCE_COLLABORATOR,
        resource_id=str(c.id),
        metadata={"previous_status": previous_status},
    )
    await session.commit()

    # #225 / ТЗ §5.1: fire `collaborator.archived`.
    await _dispatch_lifecycle_event(
        webhook_dispatcher,
        event=WebhookEvent.COLLABORATOR_ARCHIVED,
        collaborator=c,
        extras={"previous_status": previous_status},
    )


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
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
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
        actor_sub=str(claims.get("sub", "unknown")),
        action=ACTION_COLLABORATOR_ACTIVATED,
        resource_type=RESOURCE_COLLABORATOR,
        resource_id=str(c.id),
        metadata={"previous_status": previous_status},
    )
    await session.commit()

    # #225 / ТЗ §5.1: fire `collaborator.activated`.
    await _dispatch_lifecycle_event(
        webhook_dispatcher,
        event=WebhookEvent.COLLABORATOR_ACTIVATED,
        collaborator=c,
        extras={"previous_status": previous_status},
    )
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
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
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
        actor_sub=str(claims.get("sub", "unknown")),
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

    # #225 / ТЗ §5.1: fire `collaborator.suspended`.
    await _dispatch_lifecycle_event(
        webhook_dispatcher,
        event=WebhookEvent.COLLABORATOR_SUSPENDED,
        collaborator=c,
        extras={
            "previous_status": previous_status,
            "reason": payload.reason,
            "until": payload.until,
        },
    )
    return _serialize_for_scope(c, access_levels)


# ---------------------------------------------------------------------------
# Slice 3 — public onboarding + portal-access (ADR-0015, ТЗ §10.8)


@router.post(
    "/onboarding",
    status_code=status.HTTP_201_CREATED,
    response_model=OnboardingResponse,
    summary="Самозаявка коллаборанта (public, без auth)",
    responses={
        201: {"description": "Заявка принята (status=PENDING_REVIEW)"},
        422: {"description": "Невалидный type / contact / payload"},
        429: {"description": "Превышен rate-limit (5 заявок/час/IP)"},
    },
)
async def onboard_collaborator(
    payload: OnboardingRequest,
    request: Request,
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
) -> OnboardingResponse:
    """`POST /api/v1/collaborators/onboarding` — public form (ADR-0015 §6).

    Создаёт коллаборанта в статусе PENDING_REVIEW. Активация — через
    POST /activate (Slice 2) после staff review + Dadata check.

    Защита:
    - Rate-limit by IP (ADR-0015 §7): 5 заявок/час, in-memory.
    - type='other' → 422 (требует staff_invite).
    - Anti-enumeration: response только {id, status, message} —
      не возвращаем поля payload'а (защита от probing типа
      "проверь, существует ли уже ИНН в системе").
    """
    # Rate-limit + IP hash для audit.
    ip_hash = enforce_onboarding_rate_limit(request)

    # Derive financial_group (other уже отсечён в model_validator).
    financial_group = derive_financial_group(payload.type)

    c = Collaborator(
        name=payload.name,
        brand_name=payload.brand_name,
        type=payload.type,
        financial_group=financial_group,
        status="PENDING_REVIEW",
        legal_entity_type=payload.legal_entity_type,
        inn=payload.inn,
        service_area=payload.service_area,
        contacts=[payload.contact.model_dump()],
        portal_access_level="NONE",  # ставим default; staff апгрейдит при activate
        portal_access_history=[
            {
                "from": None,
                "to": "NONE",
                "by": "onboarding-form",
                "ts": datetime.now(UTC).isoformat(),
                "reason": "initial",
                "requested": payload.portal_access_level_requested,
            }
        ],
        onboarding_source="form",
        financial_terms={},
        api_integration={},
        sla={},
        counterparty_check={},
        audit_log=[],
    )
    await repo.create(c)

    await audit.record(
        actor_sub=f"anon:{ip_hash}",
        action=ACTION_COLLABORATOR_ONBOARDED,
        resource_type=RESOURCE_COLLABORATOR,
        resource_id=str(c.id),
        metadata={
            "type": c.type,
            "financial_group": c.financial_group,
            "source": "form",
            "ip_hash": ip_hash,
            "portal_access_requested": payload.portal_access_level_requested,
            "message_provided": payload.message is not None,
        },
    )
    await session.commit()

    # #225 / ТЗ §5.1: fire `collaborator.onboarding.submitted`. Payload не
    # содержит ИНН / контакты — anti-PII (subscriber может быть external).
    await _dispatch_lifecycle_event(
        webhook_dispatcher,
        event=WebhookEvent.COLLABORATOR_ONBOARDING_SUBMITTED,
        collaborator=c,
        extras={
            "source": "form",
            "portal_access_requested": payload.portal_access_level_requested,
        },
    )

    return OnboardingResponse(
        id=c.id,
        status="PENDING_REVIEW",
        message=(
            "Заявка получена. Оператор reHome рассмотрит её и свяжется "
            "по указанным контактам в течение 3 рабочих дней."
        ),
    )


# Portal-access transitions (ADR-0015 §5).
_LEVEL_ORDER = {"NONE": 0, "LIGHT": 1, "FULL": 2}


@router.put(
    "/{collaborator_id}/portal-access",
    summary="Изменить уровень кабинета коллаборанта (STAFF+)",
    responses={
        200: {"description": "Уровень изменён"},
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Не найден"},
        422: {"description": "Повышение требует reason (ТЗ §10.8.1)"},
    },
)
async def change_portal_access(
    payload: PortalAccessChangeRequest,
    collaborator_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: CollaboratorRepository = Depends(get_collaborator_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
) -> CollaboratorPublic | CollaboratorInternal | CollaboratorAdmin:
    """`PUT /api/v1/collaborators/{id}/portal-access` (ТЗ §10.8.1).

    Slice 3 — STAFF-only (Slice 4 добавит owner-flow когда landит
    collaborator user account). Понижение свободно; повышение требует
    `reason` (audit trail per ADR-0015 §5).

    History append: запись в `portal_access_history` JSONB.
    """
    allowed_groups = compute_visible_groups(access_levels)
    c = await repo.get_by_id(collaborator_id, allowed_groups)
    if c is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    current = c.portal_access_level
    target = payload.portal_access_level

    # No-op — не пишем history, не raise (idempotent).
    if current == target:
        return _serialize_for_scope(c, access_levels)

    is_promotion = _LEVEL_ORDER[target] > _LEVEL_ORDER[current]
    if is_promotion and not payload.reason:
        raise HTTPException(
            status_code=422,
            detail={
                "field": "reason",
                "message": ("Повышение tier'а требует reason " "(ТЗ §10.8.1 + ADR-0015 §5)"),
            },
        )

    history_entry = {
        "from": current,
        "to": target,
        "by": "staff",
        "ts": datetime.now(UTC).isoformat(),
        "reason": payload.reason,
    }
    new_history = [*c.portal_access_history, history_entry]

    await repo.update_fields(
        c,
        {
            "portal_access_level": target,
            "portal_access_history": new_history,
        },
        jsonb_fields=("portal_access_history",),
    )

    await audit.record(
        actor_sub=str(claims.get("sub", "unknown")),
        action=ACTION_COLLABORATOR_PORTAL_ACCESS_CHANGED,
        resource_type=RESOURCE_COLLABORATOR,
        resource_id=str(c.id),
        metadata={"from": current, "to": target, "reason": payload.reason},
    )
    await session.commit()

    # #225 / ТЗ §5.1: fire `collaborator.portal_access.changed`.
    await _dispatch_lifecycle_event(
        webhook_dispatcher,
        event=WebhookEvent.COLLABORATOR_PORTAL_ACCESS_CHANGED,
        collaborator=c,
        extras={
            "from": current,
            "to": target,
            "reason": payload.reason,
        },
    )
    return _serialize_for_scope(c, access_levels)
