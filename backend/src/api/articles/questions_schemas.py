"""Pydantic schemas для Article Q&A (ТЗ §2, 2026-05-28)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Hard caps на body sizes — anti-DoS + anti-spam через UI.
MAX_QUESTION_BODY_CHARS = 2000
MAX_ANSWER_BODY_CHARS = 5000
MAX_DISMISS_REASON_CHARS = 500


ArticleQuestionStatus = Literal["PENDING", "ANSWERED", "DISMISSED"]


class ArticleQuestionSubmitInput(BaseModel):
    """POST /api/v1/articles/{slug}/questions — body."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=MAX_QUESTION_BODY_CHARS)


class ArticleQuestionAnswerInput(BaseModel):
    """POST /api/v1/admin/article-questions/{id}/answer — body."""

    model_config = ConfigDict(extra="forbid")

    answer_body: str = Field(min_length=1, max_length=MAX_ANSWER_BODY_CHARS)


class ArticleQuestionDismissInput(BaseModel):
    """POST /api/v1/admin/article-questions/{id}/dismiss — body.

    `reason` — INTERNAL note, не показывается публично. Может содержать
    moderator's PII — guard'аем в audit metadata (не пишем body).
    """

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=MAX_DISMISS_REASON_CHARS)


class ArticleQuestionPublicView(BaseModel):
    """Public view (article detail page) — только ANSWERED видна.

    `author_sub` НЕ возвращается (privacy — анонимизация автора в публ.
    surface). Frontend показывает «User asked» без identity.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    body: str
    answer_body: str
    answered_at: datetime
    created_at: datetime


class ArticleQuestionPublicListResponse(BaseModel):
    data: list[ArticleQuestionPublicView]


class ArticleQuestionAdminView(BaseModel):
    """Admin view — все поля (включая author_sub + dismiss_reason).

    Used для admin moderation queue (/admin/article-questions).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    article_id: UUID
    author_sub: str
    body: str
    status: ArticleQuestionStatus
    answer_body: str | None = None
    answerer_sub: str | None = None
    dismiss_reason: str | None = None
    created_at: datetime
    answered_at: datetime | None = None
    updated_at: datetime


class ArticleQuestionAdminListResponse(BaseModel):
    data: list[ArticleQuestionAdminView]
    total: int  # full count для UI badge (PENDING count etc.)
