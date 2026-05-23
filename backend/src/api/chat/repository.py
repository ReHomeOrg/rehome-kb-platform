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
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.chat.models import ChatEscalation, ChatMessage, ChatSession
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
        await self._session.commit()
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

        Physical cleanup делает `ChatCleanupWorker` (#341, daily poll, env-gated)
        для soft-deleted sessions past retention; здесь только soft-delete
        + CASCADE на messages при hard-delete.
        """
        session = await self.get_session_by_owner(
            session_id, user_id=user_id, session_token=session_token
        )
        if session is None:
            return False
        session.deleted_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.commit()
        return True

    async def hard_delete_stale_sessions(
        self,
        *,
        soft_delete_retention: timedelta,
        now: datetime | None = None,
    ) -> int:
        """Background-helper: physical-DELETE chat_sessions, которые:
        - soft-deleted past retention (deleted_at < now - soft_delete_retention),
          ИЛИ
        - expired без soft-delete (expires_at < now AND deleted_at IS NULL).

        ФЗ-152 §21 right-to-forget: soft-deleted records должны быть
        physically removed после reasonable retention window (default 30d).
        Expired sessions — garbage cleanup (никто не читает их past
        expires_at filter).

        chat_messages удаляются автоматически через ForeignKey CASCADE.
        Returns count rows deleted. Caller commit'ит.
        """
        current = now or datetime.now(UTC)
        retention_cutoff = current - soft_delete_retention
        stmt = delete(ChatSession).where(
            or_(
                # Soft-deleted past retention.
                (ChatSession.deleted_at.is_not(None)) & (ChatSession.deleted_at < retention_cutoff),
                # Expired without explicit deletion.
                (ChatSession.deleted_at.is_(None)) & (ChatSession.expires_at < current),
            )
        )
        result = await self._session.execute(stmt)
        return result.rowcount or 0

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
        await self._session.commit()
        return message

    async def record_chat_turn(
        self,
        session_id: UUID,
        *,
        user_content: str,
        assistant_content: str,
        citations: list[dict[str, Any]] | None = None,
        token_count: int | None = None,
        duration_ms: int | None = None,
    ) -> ChatMessage:
        """Атомарно записать пару user+assistant в одной транзакции (E3.3).

        Используется POST /messages endpoint'ом: LLM call идёт ПЕРЕД этим
        методом, поэтому при LLM exception ни user, ни assistant НЕ
        записываются — retry-safe.

        **Precondition**: caller обязан проверить ownership session ДО
        этого вызова (через `get_session_by_owner`).

        Возвращает `assistant` сообщение (для router response).
        """
        user_msg = ChatMessage(
            session_id=session_id,
            role="user",
            content=user_content,
            citations=[],
            token_count=None,
            duration_ms=None,
        )
        assistant_msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            citations=citations or [],
            token_count=token_count,
            duration_ms=duration_ms,
        )
        self._session.add(user_msg)
        self._session.add(assistant_msg)
        await self._session.flush()
        await self._session.refresh(assistant_msg)
        await self._session.commit()
        return assistant_msg

    async def set_feedback(
        self,
        message_id: UUID,
        *,
        session_id: UUID,
        user_id: UUID | None = None,
        session_token: UUID | None = None,
        rating: str,
        comment: str | None = None,
    ) -> ChatMessage | None:
        """Установить feedback на message в session (E3.5 #69).

        Двухступенчатая авторизация:
        1. Owner-gate session через `get_session_by_owner` (None → return).
        2. message принадлежит указанной session (`WHERE session_id =`).

        404 mask: out-of-scope session ИЛИ nonexistent message ИЛИ
        cross-session message_id — все возвращают None.

        Idempotent: overwrite existing feedback без 409.
        """
        session = await self.get_session_by_owner(
            session_id, user_id=user_id, session_token=session_token
        )
        if session is None:
            return None

        stmt = (
            select(ChatMessage)
            .where(
                ChatMessage.id == message_id,
                ChatMessage.session_id == session_id,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        message = result.scalar_one_or_none()
        if message is None:
            return None

        payload: dict[str, Any] = {"rating": rating}
        if comment is not None:
            payload["comment"] = comment
        message.feedback = payload
        await self._session.flush()
        await self._session.commit()
        return message

    async def create_escalation(
        self,
        session_id: UUID,
        *,
        user_id: UUID | None = None,
        session_token: UUID | None = None,
        reason: str | None = None,
        priority: str = "normal",
    ) -> ChatEscalation | None:
        """Создать escalation ticket для session (E3.6 #71).

        Owner-gate: session должна принадлежать caller'у (через
        `get_session_by_owner`). None → return None → 404 mask.

        `user_id` (если есть) сохраняется в `requested_by_user_id` для
        audit. Anon — NULL.

        Multiple escalations allowed (без dedupe) на repo-level — каждый
        вызов создаёт новый ticket с уникальным id. Idempotency-Key
        обрабатывается на router-level через `process_chat_idempotency_key`
        (см. `chat/idempotency.py`).
        """
        session = await self.get_session_by_owner(
            session_id, user_id=user_id, session_token=session_token
        )
        if session is None:
            return None

        escalation = ChatEscalation(
            session_id=session_id,
            requested_by_user_id=user_id,
            reason=reason,
            priority=priority,
        )
        self._session.add(escalation)
        await self._session.flush()
        await self._session.refresh(escalation)
        await self._session.commit()
        return escalation


def get_chat_repository(
    session: AsyncSession = Depends(get_session),
) -> ChatRepository:
    """FastAPI Depends factory."""
    return ChatRepository(session)
