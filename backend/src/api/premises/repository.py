"""PremisesRepository — read-side foundation (#142).

ADR-0003 storage-level filter: DRAFT и ARCHIVED видимы только STAFF
(уровни STAFF / LEGAL / HR_RESTRICTED — любой из них). Others видят
только PUBLISHED + RENTED.

Write-side (create / update / archive) — follow-up PR с idempotency +
audit + RBAC.
"""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import func, select
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

    async def get_by_id(
        self,
        card_id: UUID,
        access_levels: frozenset[AccessLevel],
    ) -> PremisesCard | None:
        """Lookup по UUID id с status visibility check.

        Параллель `get_by_slug` но по id. Используется в endpoint'ах,
        принимающих `{premises_id}` path param (OpenAPI: GET /premises-cards/
        {premises_id}/financial — #226).

        Returns None если карточка не найдена ИЛИ status не виден scope'у.
        """
        statuses = self._visible_statuses(access_levels)
        stmt = (
            select(PremisesCard)
            .where(PremisesCard.id == card_id)
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

    # -------- Write side (#148) ----------------------------------------

    async def get_by_slug_raw(self, slug: str) -> PremisesCard | None:
        """Lookup БЕЗ status filter — для write side (staff видит все)."""
        result = await self._session.execute(select(PremisesCard).where(PremisesCard.slug == slug))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        slug: str,
        internal_code: str | None,
        status: str,
        address: str,
        postal_code: str | None,
        cadastral_number: str | None,
        premises_uuid: UUID | None,
        owner: dict[str, Any],
        owner_representative: dict[str, Any] | None,
        current_tenant: dict[str, Any] | None,
        financial_data: dict[str, Any],
        tenant_info: dict[str, Any],
        internal_data: dict[str, Any],
        extra_identification: dict[str, Any],
    ) -> PremisesCard:
        """INSERT новую карточку. Caller отвечает за commit.

        IntegrityError на duplicate slug → перехватывается endpoint'ом
        как 409 (стандартный pattern article repository).
        """
        card = PremisesCard(
            slug=slug,
            internal_code=internal_code,
            status=status,
            address=address,
            postal_code=postal_code,
            cadastral_number=cadastral_number,
            premises_uuid=premises_uuid,
            owner=owner,
            owner_representative=owner_representative,
            current_tenant=current_tenant,
            financial_data=financial_data,
            tenant_info=tenant_info,
            internal_data=internal_data,
            extra_identification=extra_identification,
        )
        self._session.add(card)
        await self._session.flush()
        return card

    async def update(
        self,
        slug: str,
        *,
        patch: dict[str, Any],
    ) -> PremisesCard | None:
        """Partial update. Patch dict содержит только non-None fields.

        Returns None если карточка не найдена.
        Returns updated card иначе. archived_at filter — caller'ом
        (нет смысла обновлять archived).
        """
        card = await self.get_by_slug_raw(slug)
        if card is None or card.archived_at is not None:
            return None
        for key, value in patch.items():
            setattr(card, key, value)
        card.updated_at = datetime.now(UTC)
        await self._session.flush()
        return card

    async def search(
        self,
        query: str,
        access_levels: frozenset[AccessLevel],
        *,
        limit: int = 20,
    ) -> list[tuple[PremisesCard, float]]:
        """FTS search через `websearch_to_tsquery` + ts_rank (#154).

        - `websearch_to_tsquery` — handles human-friendly syntax
          (quoted phrases, OR/AND).
        - `ts_rank(search_vector, query)` — relevance scoring.
        - ADR-0003 status filter применён (PUBLISHED+RENTED для anon,
          all для STAFF tier).

        Returns `[(card, score), ...]` sorted by score desc, limited.
        """
        statuses = self._visible_statuses(access_levels)
        tsquery = func.websearch_to_tsquery("russian", query)
        rank = func.ts_rank(PremisesCard.search_vector, tsquery).label("rank")
        stmt = (
            select(PremisesCard, rank)
            .where(
                PremisesCard.status.in_(statuses),
                PremisesCard.search_vector.op("@@")(tsquery),
            )
            .order_by(rank.desc(), PremisesCard.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [(row[0], float(row[1])) for row in result]

    async def archive(self, slug: str) -> bool:
        """Soft-delete: status='ARCHIVED' + archived_at.

        Идемпотентно: повторный archive на уже-ARCHIVED → False (404
        для caller'а).
        """
        card = await self.get_by_slug_raw(slug)
        if card is None or card.archived_at is not None:
            return False
        card.status = "ARCHIVED"
        card.archived_at = datetime.now(UTC)
        card.updated_at = datetime.now(UTC)
        await self._session.flush()
        return True


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
