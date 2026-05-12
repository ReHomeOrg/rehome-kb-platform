"""TagRepository — read-only агрегация tags из articles.tags JSONB.

КРИТИЧЕСКИЙ ИНВАРИАНТ ADR-0003: каждый SELECT, затрагивающий articles,
ДОЛЖЕН содержать `WHERE access_level IN (...)`. Здесь это включено
наравне с `status = 'PUBLISHED'`.

ADR-0008: Repository pattern обязателен. Router не работает с
AsyncSession напрямую.
"""

from fastapi import Depends
from sqlalchemy import ColumnElement, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.models import Article
from src.api.auth.scope import AccessLevel
from src.api.db import get_session


def _escape_ilike(pattern: str) -> str:
    """Экранирует `%`/`_`/`\\` чтобы user input стал буквальным substring.

    Postgres ILIKE интерпретирует `%` как «любая последовательность» и
    `_` как «один символ» — без escape пользователь мог бы матчить
    больше, чем ожидает (`q='%'` → match-all). Backslash должен быть
    экранирован первым, иначе наши вставленные `\\%`/`\\_` сами станут
    подстроками для последующих замен.
    """
    return pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class TagRepository:
    """Агрегация tags из articles + storage-level access_level filter."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_tags(
        self,
        access_levels: frozenset[AccessLevel],
        *,
        q: str | None = None,
        limit: int = 50,
    ) -> list[tuple[str, int]]:
        """Возвращает `[(tag_name, article_count), ...]`.

        Фильтрация (всегда):
        - `status = 'PUBLISHED'` — DRAFT/ARCHIVED тегов не выдаём.
        - `access_level IN (:allowed)` — ADR-0003 storage-level filter.

        Опционально:
        - `q` (substring): ILIKE-фильтр на name; `%`/`_`/`\\` экранируются,
          чтобы wildcard в user input не приводил к match-all.

        Сортировка: `article_count DESC, name ASC` — стабильна при равных
        count. Сортировка кириллицы зависит от collation БД (`ru_RU.UTF-8`
        даёт лексикографически корректный порядок; `C` collation сортирует
        по байтам — тоже стабильно, но не по алфавиту).
        """
        allowed_strings = [level.value for level in access_levels]
        if not allowed_strings:
            # IN () в Postgres всегда false → результат пуст. Возвращаем
            # раньше, чтобы не гонять SQL впустую.
            return []

        # jsonb_array_elements_text(tags) — Postgres lateral unnest JSONB-
        # массива в setof text. `column_valued("tag")` рендерится в FROM
        # (как `, jsonb_array_elements_text(articles.tags) AS tag`), что
        # делает alias `tag` доступным в SELECT/WHERE/GROUP BY.
        tag = func.jsonb_array_elements_text(Article.tags).column_valued("tag")

        count_expr = func.count(literal(1)).label("article_count")

        where_clauses: list[ColumnElement[bool]] = [
            Article.status == "PUBLISHED",
            Article.access_level.in_(allowed_strings),
        ]
        if q is not None:
            pattern = f"%{_escape_ilike(q)}%"
            where_clauses.append(tag.ilike(pattern, escape="\\"))

        stmt = (
            select(tag.label("name"), count_expr)
            .where(*where_clauses)
            .group_by(tag)
            .order_by(count_expr.desc(), tag.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [(row.name, row.article_count) for row in result.all()]


def get_tag_repository(
    session: AsyncSession = Depends(get_session),
) -> TagRepository:
    """FastAPI Depends factory для TagRepository."""
    return TagRepository(session)
