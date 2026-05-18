"""Reviews endpoints — collaborator ratings (Slice 6, ТЗ §3.10.5).

- `GET /collaborators/{id}/reviews` — public list с masked author names.
- `POST /collaborators/{id}/reviews` — auth required. Один отзыв на
  user per коллаборант (UQ in БД).

Per ТЗ §3.10.5: POST должен проверять что у user был completed
service_order. Slice 6 — без проверки (service_orders не существует).
Backlog: добавить FK + validation когда landит соответствующий epic.

Rating recompute: после INSERT/DELETE пересчитываем
`collaborators.rating` как AVG(reviews.rating). Pattern: trigger DB-level
был бы лучше, но в MVP — application-level (явный SQL).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.audit import (
    AuditRepository,
    get_audit_repository,
)
from src.api.auth.dependency import get_current_access_levels, require_authenticated
from src.api.auth.scope import AccessLevel
from src.api.collaborators.access import compute_visible_groups
from src.api.collaborators.models import Collaborator, CollaboratorReview
from src.api.db import get_session
from src.api.webhooks.dispatcher import (
    WebhookEventDispatcher,
    get_webhook_event_dispatcher,
)
from src.api.webhooks.events import WebhookEvent

router = APIRouter(prefix="/collaborators/{collaborator_id}/reviews", tags=["Collaborators"])


# Local audit constants for Slice 6.
ACTION_REVIEW_CREATED = "collaborator.review.created"
RESOURCE_REVIEW = "collaborator_review"


# ---------------------------------------------------------------------------
# Schemas — keep здесь чтобы не раздувать schemas.py


class ReviewCreateInput(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    author_display_name: str | None = Field(default=None, max_length=100)


class ReviewView(BaseModel):
    """Public view с masked author."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rating: int
    comment: str | None
    # `author_masked` — first 2 chars from display_name + "***", или "Аноним".
    author_masked: str
    created_at: Any


class ReviewsListResponse(BaseModel):
    data: list[ReviewView]
    aggregate: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers


def _mask_author(display_name: str | None) -> str:
    """`Иван Иванович` → `Ив***`. None → `Аноним`."""
    if not display_name:
        return "Аноним"
    if len(display_name) <= 2:
        return display_name + "***"
    return display_name[:2] + "***"


def _to_view(r: CollaboratorReview) -> ReviewView:
    return ReviewView(
        id=r.id,
        rating=r.rating,
        comment=r.comment,
        author_masked=_mask_author(r.author_display_name),
        created_at=r.created_at,
    )


async def _check_collaborator_visible(
    session: AsyncSession,
    collaborator_id: UUID,
    allowed_groups: frozenset[str],
) -> Collaborator | None:
    """Возвращает Collaborator только если scope видит. 404-mask pattern."""
    if not allowed_groups:
        return None
    stmt = (
        select(Collaborator)
        .where(Collaborator.id == collaborator_id)
        .where(Collaborator.financial_group.in_(list(allowed_groups)))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _recompute_rating(session: AsyncSession, collaborator_id: UUID) -> None:
    """Пересчёт `collaborators.rating` = AVG(reviews.rating).

    Если отзывов нет → rating стаёт NULL.
    """
    avg_stmt = select(func.avg(CollaboratorReview.rating)).where(
        CollaboratorReview.collaborator_id == collaborator_id
    )
    result = await session.execute(avg_stmt)
    avg_val = result.scalar_one_or_none()

    update_stmt = (
        sa_update(Collaborator).where(Collaborator.id == collaborator_id).values(rating=avg_val)
    )
    await session.execute(update_stmt)


# ---------------------------------------------------------------------------
# Endpoints


@router.get(
    "",
    response_model=ReviewsListResponse,
    summary="Отзывы о коллаборанте (public)",
)
async def list_reviews(
    collaborator_id: UUID = Path(...),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    session: AsyncSession = Depends(get_session),
) -> ReviewsListResponse:
    """`GET /api/v1/collaborators/{id}/reviews` (ТЗ §3.10.5).

    Публично доступны с маскированием author_display_name. 404 mask
    если коллаборант out-of-scope.

    Aggregate: count + avg_rating (denormalized для frontend convenience).
    """
    allowed_groups = compute_visible_groups(access_levels)
    collab = await _check_collaborator_visible(session, collaborator_id, allowed_groups)
    if collab is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    list_stmt = (
        select(CollaboratorReview)
        .where(CollaboratorReview.collaborator_id == collaborator_id)
        .order_by(CollaboratorReview.created_at.desc())
        .limit(100)  # MVP — без cursor pagination, backlog
    )
    result = await session.execute(list_stmt)
    reviews = list(result.scalars().all())

    aggregate = {
        "count": len(reviews),
        "avg_rating": float(collab.rating) if collab.rating is not None else None,
    }
    return ReviewsListResponse(
        data=[_to_view(r) for r in reviews],
        aggregate=aggregate,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ReviewView,
    summary="Оставить отзыв (LOGGED+)",
    responses={
        201: {"description": "Отзыв сохранён + rating пересчитан"},
        401: {"description": "Требуется auth"},
        404: {"description": "Collaborator out-of-scope или не существует"},
        409: {"description": "Вы уже оставляли отзыв об этом коллаборанте"},
    },
)
async def create_review(
    payload: ReviewCreateInput,
    collaborator_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    session: AsyncSession = Depends(get_session),
    audit: AuditRepository = Depends(get_audit_repository),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
) -> ReviewView:
    """`POST /api/v1/collaborators/{id}/reviews` — auth required.

    Slice 6 НЕ проверяет наличие completed service_order у автора
    (per ТЗ §3.10.5 требование) — service_orders не существует.
    Backlog: добавить FK + validation после landing'а эпика.

    После INSERT — пересчёт `collaborators.rating`.
    """
    allowed_groups = compute_visible_groups(access_levels)
    collab = await _check_collaborator_visible(session, collaborator_id, allowed_groups)
    if collab is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    author_sub = str(claims.get("sub", "unknown"))
    review = CollaboratorReview(
        collaborator_id=collaborator_id,
        author_sub=author_sub,
        author_display_name=payload.author_display_name,
        rating=payload.rating,
        comment=payload.comment,
    )
    session.add(review)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Вы уже оставляли отзыв об этом коллаборанте",
        ) from None

    await _recompute_rating(session, collaborator_id)

    await audit.record(
        actor_sub=author_sub,
        action=ACTION_REVIEW_CREATED,
        resource_type=RESOURCE_REVIEW,
        resource_id=str(review.id),
        metadata={"collaborator_id": str(collaborator_id), "rating": payload.rating},
    )
    await session.commit()

    # #225 / ТЗ §5.1: fire `collaborator.review.posted`. Payload содержит
    # ТОЛЬКО rating + collaborator_id + review_id (без comment text — comment
    # потенциально содержит ПДн / sensitive feedback; subscribers идут в
    # KB через GET /reviews если им нужен текст).
    await webhook_dispatcher.dispatch(
        event_type=WebhookEvent.COLLABORATOR_REVIEW_POSTED.value,
        payload={
            "review_id": str(review.id),
            "collaborator_id": str(collaborator_id),
            "rating": payload.rating,
            "created_at": review.created_at.isoformat(),
        },
    )
    return _to_view(review)


__all__ = [
    "ACTION_REVIEW_CREATED",
    "RESOURCE_REVIEW",
    "ReviewCreateInput",
    "ReviewView",
    "ReviewsListResponse",
    "router",
]
