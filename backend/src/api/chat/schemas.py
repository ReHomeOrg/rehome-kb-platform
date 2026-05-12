"""Pydantic схемы для `/api/v1/chat/sessions/*` (E3.2 #63).

Соответствуют OpenAPI 04 `ChatSession` (line 3433) и `ChatMessage` (3457).

ВАЖНО: `session_token` НЕ exposes в response body — только в
`X-Chat-Session-Token` header (для anon POST). Это minimization
exposure для secret-категории.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from src.api.chat.models import ChatMessage, ChatSession


class ChatContext(BaseModel):
    """Контекст открытия чата — откуда пользователь его вызвал.

    Все поля optional — клиент может не передать ничего (просто `{}`).
    """

    model_config = ConfigDict(extra="forbid")

    page_url: HttpUrl | None = None
    premises_id: UUID | None = None
    booking_id: UUID | None = None


class CreateSessionInput(BaseModel):
    """Payload для POST /chat/sessions (опциональный)."""

    model_config = ConfigDict(extra="forbid")

    context: ChatContext | None = None


# Content bounds из OpenAPI 04 (line 950-952): minLength=1, maxLength=2000.
# Defence-in-depth: те же ограничения и в этом Pydantic model, и в БД
# (chat_messages.content TEXT, без CHECK на длину — Pydantic 422 ловит).
_CONTENT_MIN_LENGTH = 1
_CONTENT_MAX_LENGTH = 2000


class SendMessageInput(BaseModel):
    """Payload для POST /chat/sessions/{id}/messages."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=_CONTENT_MIN_LENGTH, max_length=_CONTENT_MAX_LENGTH)


class ChatSessionResponse(BaseModel):
    """ChatSession в response (без session_token для security)."""

    id: UUID
    user_id: UUID | None
    scope: str
    context: dict[str, Any]
    created_at: datetime
    expires_at: datetime

    @classmethod
    def from_model(cls, session: ChatSession) -> "ChatSessionResponse":
        return cls(
            id=session.id,
            user_id=session.user_id,
            scope=session.scope,
            context=session.context,
            created_at=session.created_at,
            expires_at=session.expires_at,
        )


class ChatMessageResponse(BaseModel):
    """ChatMessage в response."""

    id: UUID
    role: str
    content: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    feedback: dict[str, Any] | None = None
    token_count: int | None = None
    duration_ms: int | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, message: ChatMessage) -> "ChatMessageResponse":
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            citations=message.citations,
            feedback=message.feedback,
            token_count=message.token_count,
            duration_ms=message.duration_ms,
            created_at=message.created_at,
        )


class ChatSessionDetailResponse(ChatSessionResponse):
    """Detail-response = session + список messages.

    Соответствует OpenAPI GET /chat/sessions/{id} response shape.
    """

    messages: list[ChatMessageResponse] = Field(default_factory=list)

    @classmethod
    def from_models(
        cls,
        session: ChatSession,
        messages: list[ChatMessage],
    ) -> "ChatSessionDetailResponse":
        return cls(
            id=session.id,
            user_id=session.user_id,
            scope=session.scope,
            context=session.context,
            created_at=session.created_at,
            expires_at=session.expires_at,
            messages=[ChatMessageResponse.from_model(m) for m in messages],
        )
