"""ArticleRepository — единственная точка доступа к таблице articles.

КРИТИЧЕСКИЙ ИНВАРИАНТ ADR-0003: ВСЕ запросы к articles фильтруются по
`access_level IN (...)` на уровне SQL, не на уровне Python.

Repository обязателен (см. ADR-0008 «Repository pattern обязателен»):
router'ы не имеют права работать напрямую с AsyncSession. Это защита
от обхода фильтрации в обход type-system.
"""

from datetime import datetime
from uuid import UUID

from fastapi import Depends
from sqlalchemy import literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.models import Article
from src.api.auth.scope import AccessLevel
from src.api.db import get_session


class ArticleRepository:
    """Read-only репозиторий статей.

    Write-операции (POST/PUT/PATCH/DELETE) появятся в E4 как отдельные
    методы; на E2.1 — только чтение.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_slug(
        self,
        slug: str,
        access_levels: frozenset[AccessLevel],
    ) -> Article | None:
        """Получить опубликованную статью по slug.

        Фильтрация:
        - `slug = :slug` — точное совпадение
        - `status = 'PUBLISHED'` — DRAFT/ARCHIVED невидимы
        - `access_level IN (:allowed_levels)` — ADR-0003 storage-level

        Если для текущего scope нет ни одного подходящего level
        (например, frozenset пустой) — фильтр `IN ()` вернёт 0 строк
        автоматически, мы возвращаем None → router отдаёт 404.

        Возвращает None если статья не существует ИЛИ scope не видит её
        (см. ADR-0003 «404 вместо 403» — маскировка существования).
        """
        allowed_strings = [level.value for level in access_levels]
        stmt = (
            select(Article)
            .where(
                Article.slug == slug,
                Article.status == "PUBLISHED",
                Article.access_level.in_(allowed_strings),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_filtered(
        self,
        access_levels: frozenset[AccessLevel],
        *,
        category: str | None = None,
        audience: str | None = None,
        language: str | None = None,
        cursor: tuple[datetime, UUID] | None = None,
        limit: int = 20,
    ) -> tuple[list[Article], bool]:
        """Возвращает страницу опубликованных статей + флаг `has_more`.

        Фильтрация (всегда):
        - `status = 'PUBLISHED'` — DRAFT/ARCHIVED скрыты на SQL-уровне.
        - `access_level IN (:allowed)` — ADR-0003 critical invariant.

        Опциональные фильтры: `category`, `audience`, `language` (если None
        — не добавляем условие, не используем `OR ... IS NULL`).

        Пагинация — keyset по композитному ключу `(updated_at DESC, id DESC)`.
        Если `cursor` задан, добавляется row-value предикат
        `(updated_at, id) < (:c_u, :c_i)` через `sqlalchemy.tuple_` — это
        row-value comparison, НЕ `AND` (последнее ломает keyset).

        Concurrent INSERT: новые статьи с `updated_at > last_returned` просто
        попадут на следующую страницу. Дубликатов/пропусков нет, потому что
        sort key стабилен и cursor хранит точную нижнюю границу.

        Возвращает `(rows, has_more)`. Запрашиваем `limit + 1` строк: если
        получили больше limit — есть следующая страница, `cursor_next` строит
        router из последнего элемента `rows[:limit]`.
        """
        allowed_strings = [level.value for level in access_levels]
        stmt = select(Article).where(
            Article.status == "PUBLISHED",
            Article.access_level.in_(allowed_strings),
        )
        if category is not None:
            stmt = stmt.where(Article.category == category)
        if audience is not None:
            stmt = stmt.where(Article.audience == audience)
        if language is not None:
            stmt = stmt.where(Article.language == language)
        if cursor is not None:
            cursor_updated_at, cursor_id = cursor
            # `literal(...)` оборачивает Python-значения в ColumnElement —
            # type-system'но корректно, и сохраняет row-value comparison
            # `(a, b) < (x, y)` вместо разворачивания в AND.
            stmt = stmt.where(
                tuple_(Article.updated_at, Article.id)
                < tuple_(literal(cursor_updated_at), literal(cursor_id))
            )
        stmt = stmt.order_by(Article.updated_at.desc(), Article.id.desc()).limit(limit + 1)
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more


def get_article_repository(
    session: AsyncSession = Depends(get_session),
) -> ArticleRepository:
    """FastAPI Depends-factory для ArticleRepository.

    Router'ы используют ИМЕННО эту dependency, не `get_session` напрямую —
    так инвариант ADR-0008 «router не работает с AsyncSession» защищён
    type-system'ом: signature endpoint'а не содержит AsyncSession.
    """
    return ArticleRepository(session)
