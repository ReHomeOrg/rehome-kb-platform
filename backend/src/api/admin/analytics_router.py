"""Admin analytics dashboard endpoints (2026-05-28, ТЗ §2 KB usage observability).

In-app dashboard — surfaces actual KB usage patterns без поднятия
external Grafana / Loki:

- `GET /api/v1/admin/analytics/queries` — top search queries в window,
  с breakdown «has_results vs no_results» (content gap signal).
- `GET /api/v1/admin/analytics/article-questions` — per-article Q&A
  counts (PENDING / ANSWERED / DISMISSED), сортировка по PENDING DESC
  (moderation backlog signal).

Pure read endpoints — no audit log (read'ы admin данных audit'ятся
middleware-level в audit_log; не нужно дублировать).

RBAC: STAFF_ADMIN (STAFF + LEGAL) — те же scopes, что и admin/stats.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from src.api.articles.questions_repository import (
    ArticleQuestionRepository,
    get_article_question_repository,
)
from src.api.auth.dependency import (
    get_current_access_levels,
    require_authenticated,
)
from src.api.auth.scope import AccessLevel
from src.api.search.query_log import (
    SearchQueryLogRepository,
    get_search_query_log_repository,
)

router = APIRouter(prefix="/admin/analytics", tags=["Admin"])


def _require_staff_admin(access_levels: frozenset[AccessLevel]) -> None:
    if not (AccessLevel.STAFF in access_levels and AccessLevel.LEGAL in access_levels):
        raise HTTPException(
            status_code=403,
            detail="Требуется staff_admin scope",
        )


# ---------------------------------------------------------------------------
# Schemas


class TopQueryView(BaseModel):
    """Одна row top-query со breakdown по результативности."""

    model_config = ConfigDict(extra="forbid")

    query: str
    total: int
    with_results: int
    without_results: int


class TopQueriesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_hours: int
    data: list[TopQueryView]


class ArticleQuestionsCountView(BaseModel):
    """Per-article Q&A counts."""

    model_config = ConfigDict(extra="forbid")

    article_id: UUID
    slug: str
    title: str
    pending: int
    answered: int
    dismissed: int
    total: int


class ArticleQuestionsCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: list[ArticleQuestionsCountView]


# ---------------------------------------------------------------------------
# Endpoints


@router.get(
    "/queries",
    response_model=TopQueriesResponse,
    summary="Top search queries with results breakdown (STAFF_ADMIN)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
    },
)
async def get_top_queries(
    window_hours: int = Query(default=168, ge=1, le=24 * 30),
    limit: int = Query(default=50, ge=1, le=200),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: SearchQueryLogRepository = Depends(get_search_query_log_repository),
) -> TopQueriesResponse:
    """`GET /api/v1/admin/analytics/queries` — top search queries.

    Window default 168h (7 days). Каждая query — `total` count и
    `with_results` count; `total - with_results` = «без ответа»
    (content gap candidate).
    """
    _require_staff_admin(access_levels)
    rows = await repo.find_top_queries(window_hours=window_hours, limit=limit)
    return TopQueriesResponse(
        window_hours=window_hours,
        data=[
            TopQueryView(
                query=q,
                total=total,
                with_results=with_results,
                without_results=total - with_results,
            )
            for (q, total, with_results) in rows
        ],
    )


@router.get(
    "/article-questions",
    response_model=ArticleQuestionsCountResponse,
    summary="Q&A counts per article (moderation backlog signal)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется staff_admin scope"},
    },
)
async def get_article_questions_counts(
    limit: int = Query(default=50, ge=1, le=200),
    _claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ArticleQuestionRepository = Depends(get_article_question_repository),
) -> ArticleQuestionsCountResponse:
    """`GET /api/v1/admin/analytics/article-questions` — per-article Q&A.

    Sorted by `pending DESC` — staff видит статьи с максимальным
    moderation backlog первыми. Articles без вопросов исключены.
    """
    _require_staff_admin(access_levels)
    rows = await repo.count_by_article(limit=limit)
    return ArticleQuestionsCountResponse(
        data=[
            ArticleQuestionsCountView(
                article_id=article_id,
                slug=slug,
                title=title,
                pending=pending,
                answered=answered,
                dismissed=dismissed,
                total=pending + answered + dismissed,
            )
            for (article_id, slug, title, pending, answered, dismissed) in rows
        ]
    )


__all__ = ["router"]
