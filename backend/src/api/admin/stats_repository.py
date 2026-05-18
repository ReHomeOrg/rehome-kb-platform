"""AdminStatsRepository — aggregator queries для GET /admin/stats (#227).

Каждая метрика — отдельный COUNT/AVG SQL запрос с time-window фильтром.
Не один большой JOIN: window'ы on разных таблицах, joining'и сложнее
читать чем sequence of small queries.

Window: `[from, to)` — exclusive upper bound (стандартная convention).

Поля без БД-источника (`requests.*`, `chat.no_answer_count`,
`security.*`) — НЕ запрашиваются: возвращаются дефолтные 0 из Pydantic.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.models import Article
from src.api.chat.models import ChatEscalation, ChatMessage, ChatSession
from src.api.db import get_session
from src.api.documents.models import Document


class AdminStatsRepository:
    """Stats aggregator. Pure read-only — никаких mutating queries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_articles_total_and_drafts(self) -> tuple[int, int]:
        """`(total_published, drafts)` — не window'ed (текущий снэпшот).

        Articles count — это catalog size, не временная метрика.
        `pending_reviews` интерпретируется как DRAFT count (нет review queue
        feature — backlog).
        """
        total_stmt = select(func.count(Article.id)).where(Article.status == "PUBLISHED")
        drafts_stmt = select(func.count(Article.id)).where(Article.status == "DRAFT")
        total_res = await self._session.execute(total_stmt)
        drafts_res = await self._session.execute(drafts_stmt)
        return int(total_res.scalar() or 0), int(drafts_res.scalar() or 0)

    async def count_documents_total(self) -> int:
        """Всего документов (DRAFT + ACTIVE + EXPIRED, без CANCELLED).

        Document.status в БД: 'DRAFT' | 'ACTIVE' | 'EXPIRED' | 'CANCELLED'.
        CANCELLED не считаем — это «удалён» semantically.
        """
        stmt = select(func.count(Document.id)).where(
            Document.status.in_(("DRAFT", "ACTIVE", "EXPIRED"))
        )
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)

    async def count_chat_sessions(self, *, from_: datetime, to: datetime) -> int:
        """Chat sessions созданные в window [from, to). Soft-deleted
        excluded (right-to-forget signal)."""
        stmt = select(func.count(ChatSession.id)).where(
            and_(
                ChatSession.created_at >= from_,
                ChatSession.created_at < to,
                ChatSession.deleted_at.is_(None),
            )
        )
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)

    async def count_chat_messages(self, *, from_: datetime, to: datetime) -> int:
        stmt = select(func.count(ChatMessage.id)).where(
            and_(ChatMessage.created_at >= from_, ChatMessage.created_at < to)
        )
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)

    async def count_chat_escalations(self, *, from_: datetime, to: datetime) -> int:
        """ChatEscalation rows в window. Эскалация = пользователь запросил
        оператора (chat.escalated event)."""
        stmt = select(func.count(ChatEscalation.id)).where(
            and_(
                ChatEscalation.requested_at >= from_,
                ChatEscalation.requested_at < to,
            )
        )
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)

    async def chat_rating_up_and_total(
        self, *, from_: datetime, to: datetime
    ) -> tuple[int, int]:
        """`(up_count, total_feedback)` для chat messages в window.

        avg_rating вычисляется caller'ом: `up / total` (0..1 scale).
        2 COUNT'а вместо одного AVG с CASE expression — проще и readable.

        feedback структура: `{rating: 'up'|'down', comment?}` JSONB.
        """
        feedback_not_null = ChatMessage.feedback.is_not(None)
        time_window = and_(
            ChatMessage.created_at >= from_,
            ChatMessage.created_at < to,
        )

        up_stmt = select(func.count(ChatMessage.id)).where(
            and_(
                feedback_not_null,
                time_window,
                # JSONB extract: feedback->>'rating' = 'up'
                ChatMessage.feedback["rating"].astext == "up",
            )
        )
        total_stmt = select(func.count(ChatMessage.id)).where(
            and_(feedback_not_null, time_window)
        )

        up_res = await self._session.execute(up_stmt)
        total_res = await self._session.execute(total_stmt)
        return int(up_res.scalar() or 0), int(total_res.scalar() or 0)


def get_admin_stats_repository(
    session: AsyncSession = Depends(get_session),
) -> AdminStatsRepository:
    return AdminStatsRepository(session)


__all__ = [
    "AdminStatsRepository",
    "get_admin_stats_repository",
]
