"""FastAPI router для `/api/v1/premises-cards/*` (#142 read + #148 write).

Read endpoints + write endpoints (POST/PATCH/DELETE) с per-scope
projection / staff-only RBAC. Slug pattern идентичен articles.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.audit import (
    ACTION_PREMISES_ARCHIVED,
    ACTION_PREMISES_CREATED,
    ACTION_PREMISES_UPDATED,
    RESOURCE_PREMISES_CARD,
    AuditRepository,
    get_audit_repository,
)
from src.api.auth.dependency import (
    get_current_access_levels,
    get_current_scope,
    require_access_level,
    require_authenticated,
)
from src.api.auth.scope import AccessLevel, Scope
from src.api.db import get_session
from src.api.idempotency import IdempotencyResult, process_idempotency_key
from src.api.premises.repository import (
    PremisesRepository,
    decode_cursor,
    encode_cursor,
    get_premises_repository,
)
from src.api.premises.schemas import (
    FinancialBlock,
    PaginationInfo,
    PremisesInput,
    PremisesListResponse,
    PremisesPatch,
    PremisesSearchHit,
    PremisesSearchInput,
    PremisesSearchResponse,
    PremisesSummary,
    PremisesView,
    project_for_scope,
)
from src.api.webhooks.dispatcher import (
    WebhookEventDispatcher,
    get_webhook_event_dispatcher,
)

logger = logging.getLogger(__name__)

# Slug pattern — defence-in-depth против path-injection (ORM
# параметризует и так, но literal validation легче анализировать).
SLUG_PATTERN = r"^[a-z0-9-]+$"

router = APIRouter(prefix="/premises-cards", tags=["Premises"])


@router.get(
    "/{slug}",
    response_model=PremisesView,
    summary="Получить карточку квартиры по slug",
    responses={
        404: {"description": "Карточка не найдена или скрыта от scope"},
    },
)
async def get_premises_card(
    slug: str = Path(..., pattern=SLUG_PATTERN, min_length=1, max_length=200),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: PremisesRepository = Depends(get_premises_repository),
) -> PremisesView:
    """Read endpoint с per-scope block projection.

    - Anon / tenant / landlord scope → identification subset only.
    - STAFF scope → все blocks (включая financial / tenant_info /
      internal_data + ПДн owner/representative/current_tenant).
    - DRAFT / ARCHIVED — невидимы для non-STAFF (404). STAFF видит все
      статусы для админских задач.
    """
    card = await repo.get_by_slug(slug, access_levels)
    if card is None:
        raise HTTPException(status_code=404, detail="Premises card not found")
    return project_for_scope(card, access_levels)


# ---------------------------------------------------------------------------
# Financial block (#226, ТЗ §3.5 / §5.2, OpenAPI 04 §FinancialBlock)


def _can_view_financial(scope: Scope, access_levels: frozenset[AccessLevel]) -> bool:
    """Доступ к финансовому блоку — landlord (свои) и staff (ТЗ §3.5).

    Stage 1: ownership-check у landlord'а отсутствует (нет `owner_user_id`
    FK в premises_cards). Поэтому landlord видит финансовый блок ЛЮБОЙ
    видимой карточки. Backlog (когда landит kb-users): добавить
    `owner_user_id` + сравнение с jwt.sub.

    Staff (STAFF/LEGAL/HR) — видят все, как и в `project_for_scope`.
    """
    staff_levels = {AccessLevel.STAFF, AccessLevel.LEGAL, AccessLevel.HR_RESTRICTED}
    if access_levels & staff_levels:
        return True
    return scope == Scope.LANDLORD


@router.get(
    "/{premises_id}/financial",
    response_model=FinancialBlock,
    summary="Финансовый блок карточки (landlord / staff)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Scope не landlord / staff"},
        404: {"description": "Карточка не найдена ИЛИ scope не видит её status"},
    },
)
async def get_premises_financial(
    premises_id: UUID = Path(...),
    _claims: dict[str, Any] = Depends(require_authenticated),
    scope: Scope = Depends(get_current_scope),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: PremisesRepository = Depends(get_premises_repository),
) -> FinancialBlock:
    """`GET /api/v1/premises-cards/{premises_id}/financial` (ТЗ §3.5, ПЗ §5.2).

    Финансовая информация по договору: monthly_rent, contract URLs,
    payment_history, service_fee (не залог — невозвратный платёж reHome
    при заезде), insurance policy.

    Auth model:
    - 401 — нет JWT.
    - 403 — scope не landlord, не staff (`tenant` / `guest` / `agent`).
    - 404 — premises не существует ИЛИ scope не видит её status
      (ADR-0003 anti-enumeration mask).

    Empty `financial_data` JSONB → возвращаем `FinancialBlock` с дефолтными
    null-полями (frontend нормально handle'ит — карточка без контракта).
    """
    if not _can_view_financial(scope, access_levels):
        raise HTTPException(
            status_code=403,
            detail="Финансовый блок доступен только landlord (свои) и staff",
        )

    card = await repo.get_by_id(premises_id, access_levels)
    if card is None:
        raise HTTPException(status_code=404, detail="Premises card not found")

    # `financial_data` — JSONB; FinancialBlock(extra='ignore') tolerates
    # unknown keys + missing keys (frontend forward-compat).
    return FinancialBlock.model_validate(card.financial_data or {})


@router.get(
    "",
    response_model=PremisesListResponse,
    summary="Список карточек квартир (cursor pagination)",
    responses={
        400: {"description": "Невалидный cursor"},
    },
)
async def list_premises_cards(
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=20, ge=1, le=100),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: PremisesRepository = Depends(get_premises_repository),
) -> PremisesListResponse:
    """Catalog list — only identification subset (ПДн blocks never в list).

    Cursor: base64-encoded `(updated_at_iso, id)` — stable ordering при ties.
    """
    decoded = None
    if cursor is not None:
        decoded = decode_cursor(cursor)
        if decoded is None:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    rows, has_more = await repo.list_published(
        access_levels=access_levels,
        cursor=decoded,
        limit=limit,
    )

    next_cursor: str | None = None
    if rows and has_more:
        last = rows[-1]
        next_cursor = encode_cursor(last.updated_at.isoformat(), str(last.id))

    return PremisesListResponse(
        data=[PremisesSummary.model_validate(r) for r in rows],
        pagination=PaginationInfo(cursor_next=next_cursor, has_more=has_more),
    )


# ---------------------------------------------------------------------------
# Search (#154) — Postgres FTS на address / cadastral / postal


@router.post(
    "/search",
    response_model=PremisesSearchResponse,
    summary="Полнотекстовый поиск карточек (Postgres FTS)",
    responses={
        422: {"description": "Невалидный body (q empty / too long)"},
    },
)
async def search_premises_cards(
    payload: PremisesSearchInput,
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: PremisesRepository = Depends(get_premises_repository),
) -> PremisesSearchResponse:
    """`POST /api/v1/premises-cards/search` — FTS по address + cadastral.

    Russian language config — handles падежи / morfology. Score —
    `ts_rank`; clip к 1.0 если ts_rank > 1 (theoretically возможно
    на длинных query c повторяющимися словами). ADR-0003: status
    filter в SQL (anon видит PUBLISHED + RENTED, STAFF — все).
    """
    # Whitespace-only — Pydantic min_length=1 пропустит, явный 422.
    if not payload.q.strip():
        raise HTTPException(
            status_code=422,
            detail="q must not be whitespace-only",
        )
    rows = await repo.search(payload.q, access_levels, limit=payload.limit)
    return PremisesSearchResponse(
        data=[
            PremisesSearchHit(
                id=card.id,
                slug=card.slug,
                address=card.address,
                postal_code=card.postal_code,
                cadastral_number=card.cadastral_number,
                status=card.status,
                # ts_rank clipped в [0, 1] для OpenAPI consistency
                # (FTS rank теоретически > 1 на длинных query).
                score=min(max(score, 0.0), 1.0),
            )
            for card, score in rows
        ]
    )


# ---------------------------------------------------------------------------
# Write endpoints (#148) — staff_admin required


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=PremisesView,
    summary="Создать карточку квартиры (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        409: {"description": "Slug already exists"},
        422: {"description": "Невалидный payload"},
    },
)
async def create_premises_card(
    payload: PremisesInput,
    response: Response,
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: PremisesRepository = Depends(get_premises_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
) -> Any:
    """Create premises card. Staff-only (содержит ПДн в payload).

    Idempotency-Key: `process_idempotency_key` replay'ит cached response
    или 409 если retry с другим body (как articles E5.1 pattern).
    """
    if idempotency.replay is not None:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    try:
        card = await repo.create(
            slug=payload.slug,
            internal_code=payload.internal_code,
            status=payload.status,
            address=payload.address,
            postal_code=payload.postal_code,
            cadastral_number=payload.cadastral_number,
            premises_uuid=payload.premises_uuid,
            owner=payload.owner,
            owner_representative=payload.owner_representative,
            current_tenant=payload.current_tenant,
            financial_data=payload.financial_data,
            tenant_info=payload.tenant_info,
            internal_data=payload.internal_data,
            extra_identification=payload.extra_identification,
        )
    except IntegrityError as exc:
        # Single likely cause: slug uniqueness violation. Logged для
        # observability, 409 для caller.
        await session.rollback()
        logger.warning("premises.create.conflict", extra={"slug": payload.slug})
        raise HTTPException(status_code=409, detail="Slug already exists") from exc

    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_PREMISES_CREATED,
        resource_type=RESOURCE_PREMISES_CARD,
        resource_id=card.slug,
        metadata={"status": card.status},
    )
    await session.commit()

    location = f"/api/v1/premises-cards/{card.slug}"
    response.headers["Location"] = location

    view = project_for_scope(card, access_levels)
    await idempotency.save(
        status_code=status.HTTP_201_CREATED,
        body=view.model_dump(mode="json"),
        headers={"Location": location},
    )
    return view


@router.patch(
    "/{slug}",
    response_model=PremisesView,
    summary="Partial update карточки (staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        404: {"description": "Карточка не найдена / архивирована"},
        422: {"description": "Невалидный payload"},
    },
)
async def patch_premises_card(
    slug: str = Path(..., pattern=SLUG_PATTERN, min_length=1, max_length=200),
    payload: PremisesPatch = Body(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: PremisesRepository = Depends(get_premises_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
    session: AsyncSession = Depends(get_session),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
) -> Any:
    """Partial update. Только non-None поля попадают в patch dict.

    Empty body (все поля None) — no-op, возвращает текущее состояние с
    updated_at touch — это намеренно (used as "version refresh" by
    clients).

    Idempotency-Key (UUID header, ADR-0025): replay cached response без
    duplicate audit row или webhook fire.
    """
    from fastapi.responses import JSONResponse

    if idempotency.replay is not None:
        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    patch_dict = payload.model_dump(exclude_none=True)
    card = await repo.update(slug, patch=patch_dict)
    if card is None:
        raise HTTPException(status_code=404, detail="Premises card not found")

    changed_fields = sorted(patch_dict.keys())
    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_PREMISES_UPDATED,
        resource_type=RESOURCE_PREMISES_CARD,
        resource_id=card.slug,
        metadata={"fields_changed": changed_fields},
    )
    await session.commit()

    # #221 / ТЗ §5.1: fire `premises_card.updated`. Empty patch (все None)
    # → no-op (subscriber'ы ожидают изменения данных, не bare touch).
    if changed_fields:
        await webhook_dispatcher.dispatch(
            event_type="premises_card.updated",
            payload={
                "premises_id": str(card.id),
                "slug": card.slug,
                "changed_fields": changed_fields,
                "updated_at": card.updated_at.isoformat(),
            },
        )
    body = project_for_scope(card, access_levels).model_dump(mode="json")
    await idempotency.save(status_code=200, body=body)
    return JSONResponse(status_code=200, content=body)


@router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Архивировать карточку (soft-delete, staff_admin)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        404: {"description": "Карточка не найдена или уже архивирована"},
    },
)
async def archive_premises_card(
    slug: str = Path(..., pattern=SLUG_PATTERN, min_length=1, max_length=200),
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: PremisesRepository = Depends(get_premises_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Soft-delete: status=ARCHIVED + archived_at. Идемпотентно: повторный
    DELETE на уже-archived → 404 (audit trail сохраняется только при
    реальном transition'е).
    """
    archived = await repo.archive(slug)
    if not archived:
        raise HTTPException(status_code=404, detail="Premises card not found")

    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_PREMISES_ARCHIVED,
        resource_type=RESOURCE_PREMISES_CARD,
        resource_id=slug,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
