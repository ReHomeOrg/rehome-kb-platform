"""ChatRepository — двойная авторизация (user_id ИЛИ session_token).

КРИТИЧЕСКИЙ ИНВАРИАНТ (адаптация ADR-0003 под chat):
- НИКАКОЙ access не идёт без identifier владельца.
- `get_session_by_owner` — единая точка проверки. List/delete всегда
  делают этот gate сначала.
- Без user_id И без session_token → return None (защита от обхода).

ADR-0008: Repository pattern обязателен.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.chat.models import ChatMessage, ChatSession
from src.api.db import get_session

# TTL named constants (CLAUDE.md §5.2: no magic numbers).
ANON_SESSION_TTL = timedelta(hours=24)
AUTH_SESSION_TTL = timedelta(days=30)


class ChatRepository:
    """Storage layer для ChatSession + ChatMessage с двойной авторизацией.

    Все методы доступа (`get_session_by_owner`, `list_messages`,
    `soft_delete_session`) требуют хотя бы один identifier владельца
    (user_id или session_token). `append_message`/`set_feedback` —
    internal методы (вызываются ПОСЛЕ owner-check на уровне router'а
    в E3.3+), они НЕ дублируют owner-check.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(
        self,
        *,
        user_id: UUID | None,
        scope: str,
        context: dict[str, Any] | None = None,
    ) -> ChatSession:
        """Создать ChatSession.

        TTL: 24h для anon (user_id is None), 30d для authorized.
        `session_token` — всегда новый UUID v4 (даже для authorized,
        для cross-device continuation).
        """
        now = datetime.now(UTC)
        ttl = AUTH_SESSION_TTL if user_id is not None else ANON_SESSION_TTL
        session = ChatSession(
            user_id=user_id,
            session_token=uuid4(),
            scope=scope,
            context=context or {},
            expires_at=now + ttl,
        )
        self._session.add(session)
        await self._session.flush()
        await self._session.refresh(session)
        return session

    async def get_session_by_owner(
        self,
        session_id: UUID,
        *,
        user_id: UUID | None = None,
        session_token: UUID | None = None,
    ) -> ChatSession | None:
        """Owner-gated access: возвращает session, только если caller — владелец.

        Security guard: если ни user_id, ни session_token не указан —
        return None немедленно (без SQL). Защита от случайного bypass'а
        в router'ах.

        Lazy expiry / deleted filter: `expires_at > now()` И
        `deleted_at IS NULL`. Истёкшие/удалённые — невидимы (404 mask).

        Если переданы и user_id, и session_token — матчит ANY. Это
        поддерживает cross-device flow: client с сохранённым
        session_token может получить session, даже если user_id отличается
        (например, перелогинился под другим аккаунтом).
        """
        if user_id is None and session_token is None:
            return None

        now = datetime.now(UTC)
        clauses: list[Any] = [
            ChatSession.id == session_id,
            ChatSession.deleted_at.is_(None),
            ChatSession.expires_at > now,
        ]
        if user_id is not None and session_token is not None:
            clauses.append(
                or_(
                    ChatSession.user_id == user_id,
                    ChatSession.session_token == session_token,
                )
            )
        elif user_id is not None:
            clauses.append(ChatSession.user_id == user_id)
        else:
            clauses.append(ChatSession.session_token == session_token)

        stmt = select(ChatSession).where(*clauses).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def soft_delete_session(
        self,
        session_id: UUID,
        *,
        user_id: UUID | None = None,
        session_token: UUID | None = None,
    ) -> bool:
        """ФЗ-152 right-to-forget: установить deleted_at = now() при owner-match.

        Возвращает True если deletion произошёл, False если session не
        найдена / уже удалена / не принадлежит caller'у. Идемпотентно:
        повторный вызов вернёт False (deleted_at не null → not found).

        Physical cleanup делает background worker (backlog) — здесь только
        soft-delete + CASCADE на messages при future hard-delete.
        """
        session = await self.get_session_by_owner(
            session_id, user_id=user_id, session_token=session_token
        )
        if session is None:
            return False
        session.deleted_at = datetime.now(UTC)
        await self._session.flush()
        return True

    async def list_messages(
        self,
        session_id: UUID,
        *,
        user_id: UUID | None = None,
        session_token: UUID | None = None,
    ) -> list[ChatMessage]:
        """Список сообщений сессии с owner-gate.

        Gate: get_session_by_owner возвращает None → return [].
        Защищает от cross-user access без HTTP-level 403 (404 mask).
        """
        session = await self.get_session_by_owner(
            session_id, user_id=user_id, session_token=session_token
        )
        if session is None:
            return []
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def append_message(
        self,
        session_id: UUID,
        *,
        role: str,
        content: str,
        citations: list[dict[str, Any]] | None = None,
        token_count: int | None = None,
        duration_ms: int | None = None,
    ) -> ChatMessage:
        """Append message to session.

        **Precondition**: caller обязан проверить ownership ДО вызова
        (через get_session_by_owner). Этот метод НЕ делает owner-check
        повторно — он assumed-internal для E3.3 router pipeline.

        CHECK constraint на role enum — DB enforce'ит при IntegrityError.
        """
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            citations=citations or [],
            token_count=token_count,
            duration_ms=duration_ms,
        )
        self._session.add(message)
        await self._session.flush()
        await self._session.refresh(message)
        return message

    async def set_feedback(
        self,
        message_id: UUID,
        *,
        rating: str,
        comment: str | None = None,
    ) -> ChatMessage | None:
        """Установить feedback на message (E3.5 endpoint).

        **Precondition**: caller обязан проверить, что message принадлежит
        session с правильным owner. Этот метод — internal storage helper.

        Возвращает None если message_id не существует.
        """
        stmt = select(ChatMessage).where(ChatMessage.id == message_id).limit(1)
        result = await self._session.execute(stmt)
        message = result.scalar_one_or_none()
        if message is None:
            return None
        payload: dict[str, Any] = {"rating": rating}
        if comment is not None:
            payload["comment"] = comment
        message.feedback = payload
        await self._session.flush()
        return message


def get_chat_repository(
    session: AsyncSession = Depends(get_session),
) -> ChatRepository:
    """FastAPI Depends factory."""
    return ChatRepository(session)
