"""CategoryAdminRepository — CRUD + cycle detection (ADR-0024, #355).

Storage layer для admin tree mutations. Cycle detection — app-level
recursive parent_id walk (per ADR Open Q 4): categories — низко-частые
writes (admin taxonomy), DB-trigger overkill.

Soft-delete через `archived_at` column (ADR-0024 Вариант B). Hard-delete
оставлен backlog'ом до FK migration на articles.category.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.categories.models import Category
from src.api.db import get_session


class CategoryNotFoundError(LookupError):
    """404-mapped: category id не найден."""


class SlugConflictError(ValueError):
    """409-mapped: slug уже занят (UQ violation prevention)."""


class ParentNotFoundError(ValueError):
    """422-mapped: parent_id ссылается на non-existing category."""


class CycleDetectedError(ValueError):
    """422-mapped: PATCH parent_id создал бы cycle (A→B→A)."""


class ArchivedParentError(ValueError):
    """422-mapped: попытка set archived row как parent active row."""


class CategoryAdminRepository:
    """Admin CRUD operations над `categories` (ADR-0024)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, category_id: UUID) -> Category | None:
        """Returns row even если archived (admin видит всё)."""
        stmt = select(Category).where(Category.id == category_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Category | None:
        stmt = select(Category).where(Category.slug == slug)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self, *, include_archived: bool = False) -> list[Category]:
        """Admin listing — flat list, sorted by slug."""
        stmt = select(Category)
        if not include_archived:
            stmt = stmt.where(Category.archived_at.is_(None))
        stmt = stmt.order_by(Category.slug.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        slug: str,
        title: str,
        description: str | None,
        parent_id: UUID | None,
    ) -> Category:
        """Insert новую category.

        Raises:
            SlugConflictError если slug уже есть.
            ParentNotFoundError если parent_id передан но не existing.
            ArchivedParentError если parent_id ссылается на archived row.
        """
        existing = await self.get_by_slug(slug)
        if existing is not None:
            raise SlugConflictError(f"slug '{slug}' уже занят")
        if parent_id is not None:
            parent = await self.get_by_id(parent_id)
            if parent is None:
                raise ParentNotFoundError(f"parent_id {parent_id} не существует")
            if parent.archived_at is not None:
                raise ArchivedParentError(
                    f"parent_id {parent_id} — archived; нельзя set'ить как родителя"
                )
        row = Category(
            slug=slug,
            title=title,
            description=description,
            parent_id=parent_id,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return row

    async def update(
        self,
        category: Category,
        *,
        title: str | None = None,
        description: str | None = None,
        parent_id: UUID | None = None,
        parent_id_set: bool = False,
    ) -> Category:
        """Partial update. `parent_id_set=True` означает поле явно передано
        (включая `None` для "promote to root"). Иначе parent unchanged.

        Cycle detection: для parent_id changes walks parents'у chain
        от candidate parent вверх; collision с current.id → cycle.

        Raises:
            ParentNotFoundError, ArchivedParentError, CycleDetectedError.
        """
        if title is not None:
            category.title = title
        if description is not None:
            category.description = description
        if parent_id_set:
            if parent_id is not None:
                if parent_id == category.id:
                    # Это покрывает CHECK constraint, но raise early с
                    # понятным message.
                    raise CycleDetectedError("parent_id не может равняться id")
                parent = await self.get_by_id(parent_id)
                if parent is None:
                    raise ParentNotFoundError(
                        f"parent_id {parent_id} не существует"
                    )
                if parent.archived_at is not None:
                    raise ArchivedParentError(
                        f"parent_id {parent_id} — archived; нельзя set'ить как родителя"
                    )
                # Cycle detection: walk chain от parent вверх; если встретим
                # current category.id → cycle.
                await self._assert_no_cycle(start=parent.id, target=category.id)
            category.parent_id = parent_id
        await self._session.flush()
        await self._session.refresh(category)
        return category

    async def archive(self, category: Category) -> Category:
        """Soft-delete: archived_at = now(). Idempotent (повторный вызов
        no-op'ит)."""
        if category.archived_at is None:
            category.archived_at = datetime.now(UTC)
            await self._session.flush()
            await self._session.refresh(category)
        return category

    async def _assert_no_cycle(self, *, start: UUID, target: UUID) -> None:
        """Walk parent_id chain от `start` вверх к root. Если встретим
        `target` — raise CycleDetectedError.

        Защита от infinite loop через `visited` set — если возвращаемся
        в уже-visited node (corrupted data), raise — это всё равно cycle.
        Категорий мало (~100), depth обычно 2-3 — O(N) приемлемо.
        """
        visited: set[UUID] = set()
        current: UUID | None = start
        while current is not None:
            if current == target:
                raise CycleDetectedError(
                    f"PATCH создал бы cycle: {target} reachable из parent chain"
                )
            if current in visited:
                # Corrupted graph — already cycle existed без участия target;
                # тоже raise.
                raise CycleDetectedError(
                    f"pre-existing cycle в parent chain (corrupt data): {current}"
                )
            visited.add(current)
            stmt = select(Category.parent_id).where(Category.id == current)
            result = await self._session.execute(stmt)
            current = result.scalar_one_or_none()


def get_category_admin_repository(
    session: AsyncSession = Depends(get_session),
) -> CategoryAdminRepository:
    return CategoryAdminRepository(session)


__all__ = [
    "ArchivedParentError",
    "CategoryAdminRepository",
    "CategoryNotFoundError",
    "CycleDetectedError",
    "ParentNotFoundError",
    "SlugConflictError",
    "get_category_admin_repository",
]
