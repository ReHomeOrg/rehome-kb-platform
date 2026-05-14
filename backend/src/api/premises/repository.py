"""PremisesRepository — read-side foundation (#142).

ADR-0003 storage-level filter: DRAFT и ARCHIVED видимы только STAFF
(уровни STAFF / LEGAL / HR_RESTRICTED — любой из них). Others видят
только PUBLISHED + RENTED.

Write-side (create / update / archive) — follow-up PR с idempotency +
audit + RBAC.
"""

from base64 import urlsafe_b64decode, urlsafe_b64encode

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth.scope import AccessLevel
from src.api.db import get_session
from src.api.premises.models import PremisesCard

# Cursor format: base64(updated_at_iso + "|" + id) — простой ordering
# для list пагинации. Используем urlsafe чтобы не escape'ить в URL.
_CURSOR_SEP = "|"


class PremisesRepository:
    """Storage layer для premises_cards."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _visible_statuses(access_levels: frozenset[AccessLevel]) -> list[str]:
        """STAFF видят все, others — PUBLISHED + RENTED.

        ADR-0003: filter применён на уровне SQL (WHERE status IN (...)),
        не в коде Python — это invariant хранилища.
        """
        staff_levels = {AccessLevel.STAFF, AccessLevel.LEGAL, AccessLevel.HR_RESTRICTED}
        if access_levels & staff_levels:
            return ["DRAFT", "PUBLISHED", "RENTED", "ARCHIVED"]
        return ["PUBLISHED", "RENTED"]

    async def get_by_slug(
        self,
        slug: str,
        access_levels: frozenset[AccessLevel],
    ) -> PremisesCard | None:
        """Lookup по slug с status visibility check.

        Returns None если карточка не найдена ИЛИ status не виден scope'у
        (anonymous lookup на DRAFT → 404 indistinguishable от not-exist —
        ADR-0003 §"не утечка существования").
        """
        statuses = self._visible_statuses(access_levels)
        stmt = (
            select(PremisesCard)
            .where(PremisesCard.slug == slug)
            .where(PremisesCard.status.in_(statuses))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_published(
        self,
        *,
        access_levels: frozenset[AccessLevel],
        cursor: tuple[str, str] | None = None,
        limit: int = 20,
    ) -> tuple[list[PremisesCard], bool]:
        """Cursor-paginated list с ADR-0003 status filter.

        Cursor — `(updated_at_iso, id)` для stable ordering при ties.
        Returns `(items, has_more)` — `has_more` определяется через
        +1-fetch overshoot (стандартный pattern, см. articles repository).
        """
        statuses = self._visible_statuses(access_levels)
        stmt = (
            select(PremisesCard)
            .where(PremisesCard.status.in_(statuses))
            .order_by(PremisesCard.updated_at.desc(), PremisesCard.id.desc())
            .limit(limit + 1)
        )
        if cursor is not None:
            cursor_dt, cursor_id = cursor
            # Compound cursor — tie-break на id когда updated_at equal.
            # Equivalent: (updated_at, id) < (cursor_dt, cursor_id).
            stmt = stmt.where(
                (PremisesCard.updated_at < cursor_dt)
                | ((PremisesCard.updated_at == cursor_dt) & (PremisesCard.id < cursor_id))
            )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more


def get_premises_repository(
    session: AsyncSession = Depends(get_session),
) -> PremisesRepository:
    return PremisesRepository(session)


def encode_cursor(updated_at_iso: str, card_id: str) -> str:
    raw = f"{updated_at_iso}{_CURSOR_SEP}{card_id}"
    return urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str] | None:
    """Возвращает (updated_at_iso, id) или None если cursor malformed."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    parts = decoded.split(_CURSOR_SEP, 1)
    if len(parts) != 2:
        return None
    return (parts[0], parts[1])
