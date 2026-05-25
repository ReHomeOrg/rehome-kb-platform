"""CategoryRepository — read-only дерево категорий с article_count.

КРИТИЧЕСКИЙ ИНВАРИАНТ ADR-0003: подсчёт article_count для каждой категории
производится через `COUNT(...) FILTER (WHERE access_level IN (...))` —
это включает storage-level filter ДО агрегации, а не после. Категории
с нулём видимых статей попадают в ответ с `article_count=0`, что
позволяет показывать структуру даже когда scope не видит content.

ADR-0008: Repository pattern обязателен. Router не работает с
AsyncSession напрямую.
"""

from dataclasses import dataclass, field
from uuid import UUID

from fastapi import Depends
from sqlalchemy import case, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.models import Article
from src.api.auth.scope import AccessLevel
from src.api.categories.models import Category
from src.api.db import get_session


@dataclass
class CategoryNode:
    """Узел дерева — flat представление перед tree-build на Python.

    Аналог CategoryResponse, но используется внутри Repository. Конверсия
    в Pydantic-схему — в router (зависит от уровня).
    """

    id: UUID
    slug: str
    title: str
    description: str | None
    parent_id: UUID | None
    article_count: int
    children: list["CategoryNode"] = field(default_factory=list)


class CategoryRepository:
    """Чтение дерева категорий с подсчётом видимых статей."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_tree(
        self,
        access_levels: frozenset[AccessLevel],
    ) -> list[CategoryNode]:
        """Возвращает корневые узлы дерева с заполненными children.

        Один SQL запрос: LEFT JOIN articles с FILTER-агрегацией count'а
        по access_level + status. Затем O(N) tree-build на Python:
        для каждой category либо добавляем в children parent'а, либо
        в root-list.

        Empty access_levels: SQL всё равно работает корректно (`IN ()`
        в Postgres → false → article_count=0 для всех категорий, но
        структура дерева возвращается). Это сознательное решение vs
        early-return в tags: tree of categories — это структура, она
        полезна даже без видимых статей.

        Сортировка детей: `article_count DESC, slug ASC` рекурсивно.
        """
        allowed_strings = [level.value for level in access_levels]

        # FILTER (WHERE status='PUBLISHED' AND access_level IN (:allowed))
        # применяется ВНУТРИ COUNT — это ADR-0003 storage-level filter
        # на агрегации. Если scope не видит ни одного article — count=0.
        # Empty allowed_strings: `IN ()` неэкспрессив в SQL — подменяем
        # на `false()`, что даёт SQL `WHERE ... AND false` → агрегация
        # COUNT FILTER возвращает 0 для всех категорий.
        access_filter = Article.access_level.in_(allowed_strings) if allowed_strings else false()
        article_count_expr = (
            func.count(case((Article.id.isnot(None), 1), else_=None))
            .filter(
                Article.status == "PUBLISHED",
                access_filter,
            )
            .label("article_count")
        )

        stmt = (
            select(
                Category.id,
                Category.slug,
                Category.title,
                Category.description,
                Category.parent_id,
                article_count_expr,
            )
            .select_from(Category)
            .outerjoin(Article, Article.category == Category.slug)
            # ADR-0024: filter archived из public tree. Admin UI использует
            # отдельный endpoint /admin/categories с include_archived toggle.
            .where(Category.archived_at.is_(None))
            .group_by(Category.id)
            .order_by(Category.slug.asc())
        )
        result = await self._session.execute(stmt)
        rows = list(result.all())

        nodes: dict[UUID, CategoryNode] = {}
        for row in rows:
            nodes[row.id] = CategoryNode(
                id=row.id,
                slug=row.slug,
                title=row.title,
                description=row.description,
                parent_id=row.parent_id,
                article_count=row.article_count,
            )

        roots: list[CategoryNode] = []
        for node in nodes.values():
            if node.parent_id is None:
                roots.append(node)
                continue
            parent = nodes.get(node.parent_id)
            if parent is None:
                # Orphan node (parent removed concurrently / corrupted FK).
                # Treat as root для устойчивости — лучше показать чем
                # потерять. В норме ondelete='RESTRICT' не даёт удалить
                # родителя с детьми.
                roots.append(node)
            else:
                parent.children.append(node)

        _sort_recursive(roots)
        return roots


def _sort_recursive(nodes: list[CategoryNode]) -> None:
    """In-place sort на каждом уровне: article_count DESC, slug ASC.

    Применяется к roots + рекурсивно к children.
    """
    nodes.sort(key=lambda n: (-n.article_count, n.slug))
    for n in nodes:
        _sort_recursive(n.children)


def get_category_repository(
    session: AsyncSession = Depends(get_session),
) -> CategoryRepository:
    """FastAPI Depends factory для CategoryRepository."""
    return CategoryRepository(session)
