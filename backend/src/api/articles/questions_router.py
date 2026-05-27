"""Article Q&A router (ТЗ §2 community-driven help, 2026-05-28).

Endpoints:
- `POST /api/v1/articles/{slug}/questions` — submit question (logged user).
- `GET  /api/v1/articles/{slug}/questions` — public list (только ANSWERED).
- `GET  /api/v1/admin/article-questions` — moderation queue (STAFF+).
- `POST /api/v1/admin/article-questions/{id}/answer` — staff answers.
- `POST /api/v1/admin/article-questions/{id}/dismiss` — staff dismisses.

ФЗ-152 invariants:
- `body` / `answer_body` / `dismiss_reason` НЕ попадают в audit_log
  metadata (user-supplied text может содержать ПДн — phone/email).
- Public list возвращает только ANSWERED, БЕЗ `author_sub` (privacy).
- DISMISSED rows полностью скрыты от public — только admin view.

ADR-0026 atomic: handler делает один `session.commit()` после audit
record + business write.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.questions_repository import (
    ArticleQuestionRepository,
    get_article_question_repository,
)
from src.api.articles.questions_schemas import (
    ArticleQuestionAdminListResponse,
    ArticleQuestionAdminView,
    ArticleQuestionAnswerInput,
    ArticleQuestionDismissInput,
    ArticleQuestionPublicListResponse,
    ArticleQuestionPublicView,
    ArticleQuestionStatus,
    ArticleQuestionSubmitInput,
)
from src.api.articles.repository import ArticleRepository, get_article_repository
from src.api.audit import (
    ACTION_ARTICLE_QUESTION_ANSWERED,
    ACTION_ARTICLE_QUESTION_DISMISSED,
    ACTION_ARTICLE_QUESTION_SUBMITTED,
    RESOURCE_ARTICLE_QUESTION,
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

# Public-facing router (mounted под /api/v1/articles/{slug}/questions).
public_router = APIRouter(prefix="/articles", tags=["Articles"])

# Admin-facing router (mounted под /api/v1/admin/article-questions).
admin_router = APIRouter(prefix="/admin/article-questions", tags=["Admin"])


# ---------------------------------------------------------------------------
# Public endpoints


@public_router.get(
    "/{slug}/questions",
    response_model=ArticleQuestionPublicListResponse,
    summary="Q&A для статьи (только ANSWERED видны публично)",
    responses={
        404: {"description": "Article не найдена"},
    },
)
async def list_article_questions(
    slug: str = Path(..., min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    article_repo: ArticleRepository = Depends(get_article_repository),
    repo: ArticleQuestionRepository = Depends(get_article_question_repository),
) -> ArticleQuestionPublicListResponse:
    """`GET /api/v1/articles/{slug}/questions` — public.

    Возвращает только ANSWERED questions, sorted newest-first. PENDING /
    DISMISSED скрыты. Auth не требуется — public help center surface.
    `author_sub` не возвращается (privacy anonymization).
    """
    article = await article_repo.get_by_slug(slug, access_levels)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    rows = await repo.list_public_for_article(article.id, limit=limit)
    return ArticleQuestionPublicListResponse(
        data=[ArticleQuestionPublicView.model_validate(r) for r in rows]
    )


@public_router.post(
    "/{slug}/questions",
    status_code=status.HTTP_201_CREATED,
    response_model=ArticleQuestionAdminView,
    summary="Задать вопрос (требуется логин)",
    responses={
        401: {"description": "Не аутентифицирован"},
        404: {"description": "Article не найдена"},
        422: {"description": "Невалидный body"},
    },
)
async def submit_article_question(
    payload: ArticleQuestionSubmitInput,
    slug: str = Path(..., min_length=1, max_length=200),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    article_repo: ArticleRepository = Depends(get_article_repository),
    repo: ArticleQuestionRepository = Depends(get_article_question_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> ArticleQuestionAdminView:
    """`POST /api/v1/articles/{slug}/questions` — submit question.

    Status=PENDING. Public list НЕ покажет до moderation. Author
    получает свой submitted question в response (Admin view shape —
    автору доступны author_sub + body, dismiss_reason если был).

    ФЗ-152: audit_log metadata = `{question_id, article_slug}` —
    БЕЗ body (user text может содержать ПДн).
    """
    actor_sub = str(claims.get("sub", "unknown"))
    article = await article_repo.get_by_slug(slug, access_levels)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    row = await repo.create(
        article_id=article.id,
        author_sub=actor_sub,
        body=payload.body,
    )
    await audit.record(
        actor_sub=actor_sub,
        action=ACTION_ARTICLE_QUESTION_SUBMITTED,
        resource_type=RESOURCE_ARTICLE_QUESTION,
        resource_id=str(row.id),
        metadata={"article_slug": slug, "article_id": str(article.id)},
    )
    await session.commit()
    return ArticleQuestionAdminView.model_validate(row)


# ---------------------------------------------------------------------------
# Admin moderation endpoints


@admin_router.get(
    "",
    response_model=ArticleQuestionAdminListResponse,
    summary="Moderation queue (STAFF+)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется STAFF scope"},
    },
)
async def list_article_questions_admin(
    status_filter: ArticleQuestionStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _claims: dict[str, Any] = Depends(require_authenticated),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: ArticleQuestionRepository = Depends(get_article_question_repository),
) -> ArticleQuestionAdminListResponse:
    """`GET /api/v1/admin/article-questions` — staff moderation queue.

    Filter `status=PENDING` для inbox (default — все статусы).
    Пагинация offset-based — admin UI не нуждается в keyset (объём
    модерации не масштабируется как content).
    """
    rows, total = await repo.list_admin(status_filter=status_filter, limit=limit, offset=offset)
    return ArticleQuestionAdminListResponse(
        data=[ArticleQuestionAdminView.model_validate(r) for r in rows],
        total=total,
    )


@admin_router.post(
    "/{question_id}/answer",
    response_model=ArticleQuestionAdminView,
    summary="Ответить на вопрос (STAFF+ → publishes публично)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Question не найден"},
        422: {"description": "Невалидный answer_body"},
    },
)
async def answer_article_question(
    payload: ArticleQuestionAnswerInput,
    question_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: ArticleQuestionRepository = Depends(get_article_question_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> ArticleQuestionAdminView:
    """`POST /api/v1/admin/article-questions/{id}/answer` — staff answers.

    Question transitions to ANSWERED, становится public.

    ФЗ-152: audit metadata `{question_id, previous_status}` — БЕЗ
    answer_body.
    """
    actor_sub = str(claims.get("sub", "unknown"))
    existing = await repo.get_by_id(question_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Question not found")
    previous_status = existing.status
    row = await repo.mark_answered(
        question_id,
        answer_body=payload.answer_body,
        answerer_sub=actor_sub,
    )
    # mark_answered returned None only если get_by_id вернул None — уже
    # проверили выше.
    assert row is not None
    await audit.record(
        actor_sub=actor_sub,
        action=ACTION_ARTICLE_QUESTION_ANSWERED,
        resource_type=RESOURCE_ARTICLE_QUESTION,
        resource_id=str(row.id),
        metadata={
            "previous_status": previous_status,
            "article_id": str(row.article_id),
        },
    )
    await session.commit()
    return ArticleQuestionAdminView.model_validate(row)


@admin_router.post(
    "/{question_id}/dismiss",
    response_model=ArticleQuestionAdminView,
    summary="Отклонить вопрос (STAFF+; ANSWERED → 409)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Question не найден"},
        409: {"description": "ANSWERED уже опубликован — dismiss НЕ allowed"},
    },
)
async def dismiss_article_question(
    payload: ArticleQuestionDismissInput,
    question_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: ArticleQuestionRepository = Depends(get_article_question_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> ArticleQuestionAdminView:
    """`POST /api/v1/admin/article-questions/{id}/dismiss` — staff dismisses.

    Допустимый transition: PENDING → DISMISSED. ANSWERED → DISMISSED
    блокируется 409 (public users уже видели answer).

    `reason` — внутренний note для audit trail (не возвращается публ.).
    """
    actor_sub = str(claims.get("sub", "unknown"))
    existing = await repo.get_by_id(question_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Question not found")
    if existing.status == "ANSWERED":
        raise HTTPException(
            status_code=409,
            detail="ANSWERED question already public; cannot dismiss",
        )
    row = await repo.mark_dismissed(question_id, reason=payload.reason)
    assert row is not None
    await audit.record(
        actor_sub=actor_sub,
        action=ACTION_ARTICLE_QUESTION_DISMISSED,
        resource_type=RESOURCE_ARTICLE_QUESTION,
        resource_id=str(row.id),
        # `reason_provided` flag (boolean) — не value (ПДн guard).
        metadata={
            "reason_provided": payload.reason is not None,
            "article_id": str(row.article_id),
        },
    )
    await session.commit()
    return ArticleQuestionAdminView.model_validate(row)


__all__ = ["admin_router", "public_router"]
