"""FastAPI router для `/api/v1/premises-cards/*` (#142, PZ §5).

Foundation read-side endpoints. Write side (POST/PUT/PATCH/DELETE) —
follow-up PR с idempotency + audit + RBAC.

Slug pattern идентичен articles router: lowercase ASCII + цифры + дефисы.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from src.api.auth.dependency import get_current_access_levels
from src.api.auth.scope import AccessLevel
from src.api.premises.repository import (
    PremisesRepository,
    decode_cursor,
    encode_cursor,
    get_premises_repository,
)
from src.api.premises.schemas import (
    PaginationInfo,
    PremisesListResponse,
    PremisesSummary,
    PremisesView,
    project_for_scope,
)

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
