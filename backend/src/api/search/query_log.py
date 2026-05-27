"""SearchQueryLog model + repository (#220, ТЗ §5.1 search.popular_query).

Хранит normalized search queries для daily aggregation popular-unanswered
detector'ом. Запись из `POST /api/v1/search` router'а (fire-and-forget
после возврата response — анти-latency).

ФЗ-152 / anti-PII:
- Только `query_normalized` (`lower(strip(q))`), не raw text c whitespace
  / case вариациями.
- НЕ сохраняем `actor_sub` / `access_levels` — aggregate-only, не
  per-user tracking. Privacy by design: лог не отвечает на «что искал
  user X»; только «что часто искали все».
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import Boolean, DateTime, String, and_, func, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db import get_session
from src.api.db.base import Base

# Hard cap длины query — matches OpenAPI SearchInput.query max_length=500.
_QUERY_MAX_LEN = 500


class SearchQueryLog(Base):
    """Одна запись в логе поискового запроса."""

    __tablename__ = "search_query_log"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    query_normalized: Mapped[str] = mapped_column(String(_QUERY_MAX_LEN), nullable=False)
    has_results: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover (debug)
        return (
            f"<SearchQueryLog id={self.id} "
            f"q={self.query_normalized!r} has_results={self.has_results}>"
        )


@dataclass(frozen=True, slots=True)
class PopularUnansweredQuery:
    """Aggregator output row."""

    query: str
    count: int


def normalize_query(raw: str) -> str:
    """Lowercase + collapse whitespace.

    `«  Договор  Аренды »`.normalize → `«договор аренды»`.

    Возвращает строку максимум `_QUERY_MAX_LEN` (truncate'им — Pydantic
    уже отвергает > 500 на router-side, это defence-in-depth).
    """
    normalized = " ".join(raw.lower().split())
    if len(normalized) > _QUERY_MAX_LEN:
        return normalized[:_QUERY_MAX_LEN]
    return normalized


class SearchQueryLogRepository:
    """CRUD + aggregation для лога поисковых запросов."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(self, *, query: str, has_results: bool) -> None:
        """Insert одну запись. Whitespace-only query NOOP'ом (caller'а
        фильтрует router validator, но defence-in-depth)."""
        normalized = normalize_query(query)
        if not normalized:
            return
        row = SearchQueryLog(query_normalized=normalized, has_results=has_results)
        self._session.add(row)
        await self._session.flush()

    async def find_top_queries(
        self,
        *,
        window_hours: int = 168,
        limit: int = 50,
    ) -> list[tuple[str, int, int]]:
        """Top queries overall в window. Returns list of
        `(query_normalized, total_count, with_results_count)`.

        Used для admin analytics dashboard: shows what users actually
        search, и какая доля query'ев имеет результаты (proxy для
        content gap). `total - with_results` = unanswered queries.

        Ordered count desc, then alphabetical (deterministic).
        """
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        total_col = func.count().label("total")
        with_results_col = func.count(func.nullif(SearchQueryLog.has_results, False)).label(
            "with_results"
        )
        stmt = (
            select(SearchQueryLog.query_normalized, total_col, with_results_col)
            .where(SearchQueryLog.created_at >= cutoff)
            .group_by(SearchQueryLog.query_normalized)
            .order_by(total_col.desc(), SearchQueryLog.query_normalized.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            (row.query_normalized, int(row.total), int(row.with_results)) for row in result.all()
        ]

    async def find_popular_unanswered(
        self,
        *,
        window_hours: int = 24,
        min_count: int = 3,
        limit: int = 50,
    ) -> list[PopularUnansweredQuery]:
        """GROUP BY query_normalized WHERE has_results=false within window.

        Returns top queries отсортированно count desc, then alphabetical
        (deterministic для tests).

        - `window_hours`: lookback window (24 = «за последние сутки»).
        - `min_count`: minimum occurrences для попадания в event
          (3 = «3+ раз без ответа»).
        - `limit`: cap для anti-payload-bloat. Aggregator не должен
          бомбардить webhook'ами на корректный 50-item list.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        count_col = func.count().label("cnt")
        stmt = (
            select(SearchQueryLog.query_normalized, count_col)
            .where(
                and_(
                    SearchQueryLog.has_results.is_(False),
                    SearchQueryLog.created_at >= cutoff,
                )
            )
            .group_by(SearchQueryLog.query_normalized)
            .having(count_col >= min_count)
            .order_by(count_col.desc(), SearchQueryLog.query_normalized.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [
            PopularUnansweredQuery(query=row.query_normalized, count=int(row.cnt))
            for row in result.all()
        ]


def get_search_query_log_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SearchQueryLogRepository:
    return SearchQueryLogRepository(session)


__all__ = [
    "PopularUnansweredQuery",
    "SearchQueryLog",
    "SearchQueryLogRepository",
    "get_search_query_log_repository",
    "normalize_query",
]
