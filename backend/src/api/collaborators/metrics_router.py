"""Metrics endpoint — collaborator analytics (Slice 4, ТЗ §3.10.3).

`GET /api/v1/collaborators/{id}/metrics` (STAFF+) — aggregations:
- rating: avg + count + distribution (1-5 histogram)
- premises_served: count junctions
- lifecycle: current_status + activated_at

Per ТЗ §3.10.3 ещё ожидаются:
- orders by status — backlog (service_orders epic)
- revenue (group B) — backlog
- SLA actual vs declared — backlog
- complaints — backlog

В MVP returns null для всех "blocked on service_orders" полей; frontend
показывает "—" или скрывает секцию.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.dependency import get_current_access_levels, require_access_level
from src.api.auth.scope import AccessLevel
from src.api.collaborators.access import compute_visible_groups
from src.api.collaborators.models import (
    Collaborator,
    CollaboratorReview,
    PremisesCollaborator,
)
from src.api.db import get_session

router = APIRouter(prefix="/collaborators/{collaborator_id}/metrics", tags=["Collaborators"])


# ---------------------------------------------------------------------------
# Schemas


class RatingMetric(BaseModel):
    """Aggregations по reviews."""

    average: float | None
    count: int
    # Distribution {"1": int, "2": int, ..., "5": int}.
    distribution: dict[str, int]


class LifecycleMetric(BaseModel):
    current_status: str
    portal_access_level: str
    onboarding_source: str
    created_at: datetime
    updated_at: datetime


class Period(BaseModel):
    """Период для time-bounded aggregations. None = all-time."""

    model_config = ConfigDict(populate_by_name=True)

    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None


class CollaboratorMetricsResponse(BaseModel):
    """ТЗ §3.10.3 metrics response. Backlog fields null до service_orders."""

    collaborator_id: UUID
    period: Period
    rating: RatingMetric
    premises_served: int
    lifecycle: LifecycleMetric
    # ТЗ-required, но требует service_orders epic — null до landing'а.
    orders_by_status: dict[str, int] | None = None
    revenue_rub: float | None = None
    sla_actual: dict[str, Any] | None = None
    complaints_count: int | None = None


# ---------------------------------------------------------------------------
# Endpoint


@router.get(
    "",
    response_model=CollaboratorMetricsResponse,
    response_model_by_alias=True,
    summary="Метрики коллаборанта (STAFF+)",
    responses={
        200: {"description": "OK"},
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Коллаборант не найден или scope не видит"},
    },
)
async def get_collaborator_metrics(
    collaborator_id: UUID = Path(...),
    period_from: datetime | None = Query(
        default=None,
        alias="from",
        description="ISO-8601 нижняя граница периода для rating aggregation",
    ),
    period_to: datetime | None = Query(
        default=None,
        alias="to",
        description="ISO-8601 верхняя граница периода",
    ),
    _staff: None = Depends(require_access_level(AccessLevel.STAFF)),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    session: AsyncSession = Depends(get_session),
) -> CollaboratorMetricsResponse:
    """`GET /api/v1/collaborators/{id}/metrics` (ТЗ §3.10.3, STAFF+).

    Returns aggregations over reviews + junction. Time-bounded поля
    (rating) фильтруются по `from`/`to` query params. lifecycle и
    premises_served — current-state snapshots (период не применяется).
    """
    allowed_groups = compute_visible_groups(access_levels)
    if not allowed_groups:
        raise HTTPException(status_code=404, detail="Collaborator not found")
    collab_stmt = (
        select(Collaborator)
        .where(Collaborator.id == collaborator_id)
        .where(Collaborator.financial_group.in_(list(allowed_groups)))
        .limit(1)
    )
    result = await session.execute(collab_stmt)
    collab = result.scalar_one_or_none()
    if collab is None:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    # Rating aggregations — period-bounded.
    rating_stmt = select(
        func.avg(CollaboratorReview.rating).label("avg_rating"),
        func.count(CollaboratorReview.id).label("total"),
    ).where(CollaboratorReview.collaborator_id == collaborator_id)
    if period_from is not None:
        rating_stmt = rating_stmt.where(CollaboratorReview.created_at >= period_from)
    if period_to is not None:
        rating_stmt = rating_stmt.where(CollaboratorReview.created_at < period_to)
    row_mapping = (await session.execute(rating_stmt)).mappings().one()
    avg_raw = row_mapping["avg_rating"]
    avg_rating: float | None = float(avg_raw) if avg_raw is not None else None
    rating_count: int = int(row_mapping["total"])

    # Distribution by integer rating bucket.
    dist_stmt = (
        select(CollaboratorReview.rating, func.count(CollaboratorReview.id))
        .where(CollaboratorReview.collaborator_id == collaborator_id)
        .group_by(CollaboratorReview.rating)
    )
    if period_from is not None:
        dist_stmt = dist_stmt.where(CollaboratorReview.created_at >= period_from)
    if period_to is not None:
        dist_stmt = dist_stmt.where(CollaboratorReview.created_at < period_to)
    dist_rows = (await session.execute(dist_stmt)).all()
    distribution: dict[str, int] = {str(i): 0 for i in range(1, 6)}
    for rating_val, cnt in dist_rows:
        distribution[str(rating_val)] = int(cnt)

    # Premises served count — current state, не period-bounded.
    premises_stmt = select(func.count(PremisesCollaborator.id)).where(
        PremisesCollaborator.collaborator_id == collaborator_id
    )
    premises_count = int((await session.execute(premises_stmt)).scalar_one())

    return CollaboratorMetricsResponse(
        collaborator_id=collab.id,
        period=Period.model_validate({"from_": period_from, "to": period_to}),
        rating=RatingMetric(
            average=avg_rating,
            count=rating_count,
            distribution=distribution,
        ),
        premises_served=premises_count,
        lifecycle=LifecycleMetric(
            current_status=collab.status,
            portal_access_level=collab.portal_access_level,
            onboarding_source=collab.onboarding_source,
            created_at=collab.created_at,
            updated_at=collab.updated_at,
        ),
        # Backlog: после landing'а service_orders.
        orders_by_status=None,
        revenue_rub=None,
        sla_actual=None,
        complaints_count=None,
    )


__all__ = [
    "CollaboratorMetricsResponse",
    "LifecycleMetric",
    "Period",
    "RatingMetric",
    "router",
]
