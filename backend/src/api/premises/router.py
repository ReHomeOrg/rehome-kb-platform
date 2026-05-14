"""FastAPI router для `/api/v1/premises-cards/*` (#142 read + #148 write).

Read endpoints + write endpoints (POST/PATCH/DELETE) с per-scope
projection / staff-only RBAC. Slug pattern идентичен articles.
"""

import logging
from typing import Any

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
    require_access_level,
    require_authenticated,
)
from src.api.auth.scope import AccessLevel
from src.api.db import get_session
from src.api.idempotency import IdempotencyResult, process_idempotency_key
from src.api.premises.repository import (
    PremisesRepository,
    decode_cursor,
    encode_cursor,
    get_premises_repository,
)
from src.api.premises.schemas import (
    PaginationInfo,
    PremisesInput,
    PremisesListResponse,
    PremisesPatch,
    PremisesSummary,
    PremisesView,
    project_for_scope,
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
    session: AsyncSession = Depends(get_session),
) -> PremisesView:
    """Partial update. Только non-None поля попадают в patch dict.

    Empty body (все поля None) — no-op, возвращает текущее состояние с
    updated_at touch — это намеренно (used as "version refresh" by
    clients).
    """
    patch_dict = payload.model_dump(exclude_none=True)
    card = await repo.update(slug, patch=patch_dict)
    if card is None:
        raise HTTPException(status_code=404, detail="Premises card not found")

    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_PREMISES_UPDATED,
        resource_type=RESOURCE_PREMISES_CARD,
        resource_id=card.slug,
        metadata={"fields_changed": list(patch_dict.keys())},
    )
    await session.commit()
    return project_for_scope(card, access_levels)


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
