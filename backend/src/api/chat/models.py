"""SQLAlchemy ORM модели ChatSession + ChatMessage (E3.1 #61).

Соответствуют OpenAPI 04 `ChatSession` (line 3433) и `ChatMessage` (3457).

ChatSession.session_token — opaque UUID, выдаётся ВСЕГДА (даже для
authorized user — для cross-device continuation, см. docstring класса).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class ChatSession(Base):
    """Сессия AI-чата (Issue #61).

    `user_id` nullable: ChatMVP поддерживает анонимный access (Architect
    decision 2026-05-12). Owner-проверка идёт через **двойную** авторизацию:
    `user_id` (JWT `sub`) ИЛИ `session_token` (opaque UUID, выдаётся клиенту
    при CREATE и хранится в cookie/header).

    `session_token` генерируется ВСЕГДА, даже для authorized session — это
    обеспечивает cross-device continuation: anon-пользователь начал чат,
    залогинился, сессия продолжается под user_id, при этом старый client'у
    с сохранённым session_token всё ещё доступна. Дополнительные расходы:
    16 bytes на строку и один UNIQUE index — приемлемо.

    `expires_at` устанавливается в Python при create_session — 24h для
    anon, 30d для authorized. Lazy filter на read: `expires_at > now()
    AND deleted_at IS NULL`. Background cleanup-worker — backlog.

    `deleted_at` для soft-delete (ФЗ-152 right-to-forget). После deletion
    данные физически остаются в БД до background cleanup.
    """

    __tablename__ = "chat_sessions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    session_token: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        unique=True,
        nullable=False,
        index=True,
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_chat_sessions_user_created", "user_id", "created_at"),
        # Partial index для cleanup-worker (backlog) — только живые сессии.
        Index(
            "ix_chat_sessions_expires_alive",
            "expires_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return f"<ChatSession id={self.id!r} user_id={self.user_id!r}>"


class ChatMessage(Base):
    """Сообщение в сессии чата.

    Owner-check НЕ дублируется здесь (ownership на уровне ChatSession);
    repository.list_messages / append_message требуют owner-check
    `get_session_by_owner` ДО доступа к сообщениям.

    `feedback` JSONB nullable — устанавливается E3.5 endpoint'ом
    POST /chat/sessions/{id}/feedback. Структура: `{rating, comment}`.

    `citations` JSONB array — заполняется LLMProvider (E3.3+). Структура:
    `[{type, id, title, url}, ...]`.
    """

    __tablename__ = "chat_messages"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_chat_messages_role",
        ),
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return f"<ChatMessage id={self.id!r} session_id={self.session_id!r} role={self.role!r}>"

    @staticmethod
    def allowed_roles() -> tuple[str, ...]:
        """Источник истины для CHECK constraint sync (test_models_check_sync)."""
        return ("user", "assistant", "system")
