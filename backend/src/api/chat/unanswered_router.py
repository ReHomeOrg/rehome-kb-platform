"""Admin router для chat_unanswered_queries (2026-05-29).

Endpoints (все STAFF+):
- `GET  /api/v1/admin/chat-unanswered-queries` — moderation queue.
- `POST /api/v1/admin/chat-unanswered-queries/{id}/attach` — attach к
  выбранной article как новый PENDING `article_question`. Возвращает Q&A
  row для дальнейшей moderation (staff может сразу ответить через
  existing `/api/v1/admin/article-questions/{id}/answer`).
- `POST /api/v1/admin/chat-unanswered-queries/{id}/dismiss` — отметить
  как out-of-scope; не создаёт Q&A row.

ФЗ-152:
- `query_masked` уже masked при capture (см. unanswered_queries.record);
  router отдаёт masked text в admin view.
- Audit metadata НЕ содержит body / reason value — только presence flag.

ADR-0026 atomic: handler делает один `session.commit()` после audit
record + business writes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.questions_repository import (
    ArticleQuestionRepository,
    get_article_question_repository,
)
from src.api.articles.questions_schemas import (
    MAX_DISMISS_REASON_CHARS,
    MAX_QUESTION_BODY_CHARS,
    ArticleQuestionAdminView,
)
from src.api.articles.repository import ArticleRepository, get_article_repository
from src.api.audit import (
    ACTION_CHAT_UNANSWERED_ATTACHED,
    ACTION_CHAT_UNANSWERED_DISMISSED,
    RESOURCE_CHAT_UNANSWERED,
    AuditRepository,
    get_audit_repository,
)
from src.api.auth.dependency import (
    get_current_access_levels,
    require_access_level,
    require_authenticated,
)
from src.api.auth.scope import AccessLevel
from src.api.chat.unanswered_queries import (
    ChatUnansweredQueryRepository,
    get_chat_unanswered_query_repository,
)
from src.api.db import get_session

ChatUnansweredStatus = Literal["NEW", "ATTACHED", "DISMISSED"]


# ---------------------------------------------------------------------------
# Pydantic schemas


class ChatUnansweredView(BaseModel):
    """Admin view для одной row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    query_masked: str
    author_sub: str
    chat_session_id: UUID | None
    status: ChatUnansweredStatus
    attached_question_id: UUID | None = None
    attached_article_slug: str | None = None
    dismiss_reason: str | None = None
    created_at: datetime
    attached_at: datetime | None = None
    updated_at: datetime


class ChatUnansweredListResponse(BaseModel):
    data: list[ChatUnansweredView]
    total: int


class ChatUnansweredAttachInput(BaseModel):
    """POST /attach body."""

    model_config = ConfigDict(extra="forbid")

    article_slug: str = Field(min_length=1, max_length=200)
    # Опциональный override: staff может переформулировать query перед
    # созданием Q&A. Если None — используется `query_masked` как body.
    question_body: str | None = Field(default=None, max_length=MAX_QUESTION_BODY_CHARS)


class ChatUnansweredAttachResponse(BaseModel):
    """Response — отдаём созданный article_question + attached row."""

    unanswered: ChatUnansweredView
    question: ArticleQuestionAdminView


class ChatUnansweredDismissInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=MAX_DISMISS_REASON_CHARS)


# ---------------------------------------------------------------------------
# Router

admin_router = APIRouter(prefix="/admin/chat-unanswered-queries", tags=["Admin"])


@admin_router.get(
    "",
    response_model=ChatUnansweredListResponse,
    summary="Capture queue для chat queries без RAG hits (STAFF+)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется STAFF scope"},
    },
)
async def list_chat_unanswered_queries(
    status_filter: ChatUnansweredStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _claims: dict[str, Any] = Depends(require_authenticated),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: ChatUnansweredQueryRepository = Depends(get_chat_unanswered_query_repository),
) -> ChatUnansweredListResponse:
    """`GET /api/v1/admin/chat-unanswered-queries` — paginated list."""
    rows, total = await repo.list_admin(status_filter=status_filter, limit=limit, offset=offset)
    return ChatUnansweredListResponse(
        data=[ChatUnansweredView.model_validate(r) for r in rows],
        total=total,
    )


@admin_router.post(
    "/{query_id}/attach",
    response_model=ChatUnansweredAttachResponse,
    summary="Attach as PENDING ArticleQuestion under chosen article (STAFF+)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Row или article slug не найдены"},
        409: {"description": "Row уже ATTACHED / DISMISSED"},
    },
)
async def attach_chat_unanswered_query(
    payload: ChatUnansweredAttachInput = Body(...),
    query_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ChatUnansweredQueryRepository = Depends(get_chat_unanswered_query_repository),
    article_repo: ArticleRepository = Depends(get_article_repository),
    question_repo: ArticleQuestionRepository = Depends(get_article_question_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> ChatUnansweredAttachResponse:
    """`POST /api/v1/admin/chat-unanswered-queries/{id}/attach`.

    Lifecycle:
    1. Lookup row → 404 если нет; 409 если уже не NEW (already
       attached/dismissed — sticky terminal state).
    2. Lookup article by slug → 404 если нет / scope не позволяет.
    3. Create PENDING ArticleQuestion с body = `payload.question_body`
       либо `row.query_masked`; `author_sub` = original chat author
       (preserves attribution chain).
    4. mark_attached на unanswered row (FK + denormalized slug).
    5. Audit `chat.unanswered.attached` с metadata
       `{article_slug, question_id}`.

    Body Q&A row — uses `query_masked` (уже PII-safe) или staff override
    (staff override считается deliberate — может содержать ПДн если staff
    хотел; not our problem согласно §2 в audit constants).
    """
    actor_sub = str(claims.get("sub", "unknown"))
    row = await repo.get_by_id(query_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Unanswered query not found")
    if row.status != "NEW":
        raise HTTPException(status_code=409, detail=f"Row already {row.status}; cannot re-attach")

    article = await article_repo.get_by_slug(payload.article_slug, access_levels)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    question_body = payload.question_body or row.query_masked
    question = await question_repo.create(
        article_id=article.id,
        author_sub=row.author_sub,
        body=question_body,
    )
    attached = await repo.mark_attached(
        query_id,
        attached_question_id=question.id,
        attached_article_slug=article.slug,
    )
    # mark_attached returns None только если get_by_id None — уже проверено.
    assert attached is not None
    await audit.record(
        actor_sub=actor_sub,
        action=ACTION_CHAT_UNANSWERED_ATTACHED,
        resource_type=RESOURCE_CHAT_UNANSWERED,
        resource_id=str(attached.id),
        metadata={
            "article_slug": article.slug,
            "article_id": str(article.id),
            "question_id": str(question.id),
        },
    )
    await session.commit()
    return ChatUnansweredAttachResponse(
        unanswered=ChatUnansweredView.model_validate(attached),
        question=ArticleQuestionAdminView.model_validate(question),
    )


@admin_router.post(
    "/{query_id}/dismiss",
    response_model=ChatUnansweredView,
    summary="Dismiss как out-of-scope (STAFF+; ATTACHED → 409)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Требуется STAFF scope"},
        404: {"description": "Row не найдена"},
        409: {"description": "Row уже ATTACHED — нельзя dismiss"},
    },
)
async def dismiss_chat_unanswered_query(
    payload: ChatUnansweredDismissInput = Body(...),
    query_id: UUID = Path(...),
    claims: dict[str, Any] = Depends(require_authenticated),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: ChatUnansweredQueryRepository = Depends(get_chat_unanswered_query_repository),
    audit: AuditRepository = Depends(get_audit_repository),
    session: AsyncSession = Depends(get_session),
) -> ChatUnansweredView:
    """`POST /api/v1/admin/chat-unanswered-queries/{id}/dismiss`.

    NEW → DISMISSED. ATTACHED → DISMISSED блокируется 409: соответствующий
    article_question уже создан и потенциально публичен; dismiss row
    не отменит публикацию.
    """
    actor_sub = str(claims.get("sub", "unknown"))
    existing = await repo.get_by_id(query_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Unanswered query not found")
    if existing.status == "ATTACHED":
        raise HTTPException(
            status_code=409,
            detail="Row already attached to article_question; cannot dismiss",
        )
    row = await repo.mark_dismissed(query_id, reason=payload.reason)
    assert row is not None
    await audit.record(
        actor_sub=actor_sub,
        action=ACTION_CHAT_UNANSWERED_DISMISSED,
        resource_type=RESOURCE_CHAT_UNANSWERED,
        resource_id=str(row.id),
        # `reason_provided` flag (boolean) — не value (ПДн guard).
        metadata={
            "reason_provided": payload.reason is not None,
        },
    )
    await session.commit()
    return ChatUnansweredView.model_validate(row)


__all__ = ["admin_router"]
