"""chat_unanswered_queries — ORM + repository (2026-05-29).

Capture queue для chat queries которые RAG не закрыл. Admin attach'ает
их к article (создавая PENDING ArticleQuestion для последующего staff
answer'а) или dismiss'ает как out-of-scope.

ФЗ-152: `query_masked` — user query AFTER mask_pii. Repository
encapsulates это в `record()` чтобы router/handler не мог обойти guard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final, Literal
from uuid import UUID

from fastapi import Depends
from sqlalchemy import DateTime, ForeignKey, Text, and_, func, select, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.api.chat.pii_masking import mask_pii
from src.api.db import get_session
from src.api.db.base import Base

ChatUnansweredStatus = Literal["NEW", "ATTACHED", "DISMISSED"]

# DoS guard + alignment с search_query_log normalize_query truncate.
QUERY_MASKED_MAX_CHARS: Final = 500


class ChatUnansweredQuery(Base):
    """Captured chat query которая не получила RAG-grounded answer'а.

    Lifecycle: chat handler → record(NEW) → staff либо attach() (создаёт
    article_questions row) либо dismiss(). Terminal states sticky.
    """

    __tablename__ = "chat_unanswered_queries"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    query_masked: Mapped[str] = mapped_column(Text, nullable=False)
    author_sub: Mapped[str] = mapped_column(Text, nullable=False)
    chat_session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'NEW'"))
    attached_question_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("article_questions.id", ondelete="SET NULL"),
        nullable=True,
    )
    attached_article_slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    dismiss_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    attached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChatUnansweredQuery {self.id} status={self.status!r}>"


class ChatUnansweredQueryRepository:
    """Storage layer для chat_unanswered_queries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        query: str,
        author_sub: str,
        chat_session_id: UUID | None,
    ) -> ChatUnansweredQuery | None:
        """INSERT NEW row. `query` masked + truncated здесь — единственная
        точка persist'а; chat handler не может обойти.

        Returns persisted row или None если query пустой после нормализации
        (defensive — chat handler уже валидирует, но защита от race).
        Caller отвечает за commit.
        """
        masked = mask_pii(query).text.strip()
        if not masked:
            return None
        # Truncate to cap — DoS guard. Совпадает с search_query_log
        # normalize_query поведением.
        if len(masked) > QUERY_MASKED_MAX_CHARS:
            masked = masked[:QUERY_MASKED_MAX_CHARS]
        row = ChatUnansweredQuery(
            query_masked=masked,
            author_sub=author_sub,
            chat_session_id=chat_session_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_by_id(self, query_id: UUID) -> ChatUnansweredQuery | None:
        stmt = select(ChatUnansweredQuery).where(ChatUnansweredQuery.id == query_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_admin(
        self,
        *,
        status_filter: ChatUnansweredStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ChatUnansweredQuery], int]:
        """Admin moderation queue. Returns (rows, total_count).

        По default newest first. status filter — narrow на NEW для inbox.
        """
        base = select(ChatUnansweredQuery)
        if status_filter is not None:
            base = base.where(ChatUnansweredQuery.status == status_filter)
        rows_stmt = base.order_by(ChatUnansweredQuery.created_at.desc()).limit(limit).offset(offset)
        count_stmt = select(func.count()).select_from(base.subquery())

        rows_result = await self._session.execute(rows_stmt)
        rows = list(rows_result.scalars().all())
        total = (await self._session.execute(count_stmt)).scalar_one()
        return rows, int(total)

    async def find_top_normalized(
        self,
        *,
        window_hours: int = 168,
        limit: int = 50,
        status_filter: ChatUnansweredStatus | None = "NEW",
    ) -> list[tuple[str, int, datetime, datetime]]:
        """Aggregate top unanswered chat queries in time window.

        Returns `(normalized_query, count, first_seen, last_seen)` tuples
        ordered by count desc, then alphabetical (deterministic tiebreak).

        Normalization here is `lower(query_masked)`. `query_masked` is
        already stripped of edge whitespace in `record()` and PII-masked
        at capture time, so this is sufficient for grouping case
        variations. It is *not* identical to
        `search.query_log.normalize_query` which also collapses inner
        whitespace — collapsing inner whitespace via SQL across dialects
        is awkward; if we later need exact parity, add a generated
        column in a follow-up migration.

        - `window_hours`: lookback window from now (UTC).
        - `limit`: cap; pairs with router-side bound 1..200.
        - `status_filter`: default `"NEW"` to surface unhandled queue
          only. `None` aggregates across all statuses (incl. ATTACHED /
          DISMISSED) for retrospective views.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        normalized_col = func.lower(ChatUnansweredQuery.query_masked).label("normalized")
        count_col = func.count().label("cnt")
        first_seen_col = func.min(ChatUnansweredQuery.created_at).label("first_seen")
        last_seen_col = func.max(ChatUnansweredQuery.created_at).label("last_seen")

        where_clauses = [ChatUnansweredQuery.created_at >= cutoff]
        if status_filter is not None:
            where_clauses.append(ChatUnansweredQuery.status == status_filter)

        stmt = (
            select(normalized_col, count_col, first_seen_col, last_seen_col)
            .where(and_(*where_clauses))
            .group_by(normalized_col)
            .order_by(count_col.desc(), normalized_col.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            (row.normalized, int(row.cnt), row.first_seen, row.last_seen)
            for row in result.all()
        ]

    async def mark_attached(
        self,
        query_id: UUID,
        *,
        attached_question_id: UUID,
        attached_article_slug: str,
    ) -> ChatUnansweredQuery | None:
        """NEW → ATTACHED. Caller (router) уже создал ArticleQuestion и
        передаёт его id + parent article slug для denormalized display.
        Caller отвечает за commit.

        Возвращает None если row не найдена. Если row уже не в NEW —
        router отдаёт 409 (caller проверяет).
        """
        row = await self.get_by_id(query_id)
        if row is None:
            return None
        now = datetime.now(UTC)
        row.status = "ATTACHED"
        row.attached_question_id = attached_question_id
        row.attached_article_slug = attached_article_slug
        row.attached_at = now
        row.updated_at = now
        # Clear stale dismiss_reason (legitimate transition не из NEW: out
        # of scope для admin UI; всё-таки defensive — был бы set если
        # кто-то revert DISMISSED→ATTACHED через manual SQL).
        row.dismiss_reason = None
        await self._session.flush()
        return row

    async def mark_dismissed(
        self,
        query_id: UUID,
        *,
        reason: str | None,
    ) -> ChatUnansweredQuery | None:
        """NEW → DISMISSED. ATTACHED → DISMISSED router'ом блокируется
        (article_question already created — нельзя retract dismiss-style).
        Caller отвечает за commit.
        """
        row = await self.get_by_id(query_id)
        if row is None:
            return None
        if row.status == "ATTACHED":
            # Caller (router) обрабатывает 409.
            return row
        now = datetime.now(UTC)
        row.status = "DISMISSED"
        row.dismiss_reason = reason
        row.updated_at = now
        await self._session.flush()
        return row


def get_chat_unanswered_query_repository(
    session: AsyncSession = Depends(get_session),
) -> ChatUnansweredQueryRepository:
    return ChatUnansweredQueryRepository(session)


__all__ = [
    "QUERY_MASKED_MAX_CHARS",
    "ChatUnansweredQuery",
    "ChatUnansweredQueryRepository",
    "ChatUnansweredStatus",
    "get_chat_unanswered_query_repository",
]
