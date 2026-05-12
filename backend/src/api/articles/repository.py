"""ArticleRepository — единственная точка доступа к таблице articles.

КРИТИЧЕСКИЙ ИНВАРИАНТ ADR-0003: ВСЕ запросы к articles фильтруются по
`access_level IN (...)` на уровне SQL, не на уровне Python.

Repository обязателен (см. ADR-0008 «Repository pattern обязателен»):
router'ы не имеют права работать напрямую с AsyncSession. Это защита
от обхода фильтрации в обход type-system.
"""

from fastapi import Depends
from sqlalchemy import select
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


def get_article_repository(
    session: AsyncSession = Depends(get_session),
) -> ArticleRepository:
    """FastAPI Depends-factory для ArticleRepository.

    Router'ы используют ИМЕННО эту dependency, не `get_session` напрямую —
    так инвариант ADR-0008 «router не работает с AsyncSession» защищён
    type-system'ом: signature endpoint'а не содержит AsyncSession.
    """
    return ArticleRepository(session)
