"""Unit-тесты CategoryRepository.

Покрывает (ADR-0003 invariants):
1. SQL содержит `access_level IN (...)` в FILTER clause.
2. SQL содержит `status = 'PUBLISHED'` в FILTER.
3. LEFT OUTER JOIN articles ON articles.category = categories.slug.
4. GROUP BY на categories.id.
5. Empty access_levels: SQL гонится, но article_count=0 для всех.
6. Tree-build: flat list → hierarchical.
7. Сортировка: article_count DESC, slug ASC на каждом уровне.
8. Orphan node (parent_id указывает на несуществующего родителя) → root.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.auth.scope import AccessLevel
from src.api.categories.repository import (
    CategoryNode,
    CategoryRepository,
    _sort_recursive,
)


@pytest.fixture
def empty_session() -> Any:
    """Session с empty result."""
    result = MagicMock()
    result.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _make_row(
    slug: str, parent_id: Any = None, article_count: int = 0, title: str | None = None
) -> MagicMock:
    r = MagicMock()
    r.id = uuid4()
    r.slug = slug
    r.title = title or slug.capitalize()
    r.description = None
    r.parent_id = parent_id
    r.article_count = article_count
    return r


def _session_returning(rows: list[MagicMock]) -> Any:
    result = MagicMock()
    result.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# SQL inspect (ADR-0003 invariants)


@pytest.mark.asyncio
@pytest.mark.security
async def test_list_tree_sql_includes_filter_with_access_level_and_status(
    empty_session: Any,
) -> None:
    """ADR-0003: COUNT FILTER должен включать access_level IN + status='PUBLISHED'."""
    repo = CategoryRepository(empty_session)
    await repo.list_tree(frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED}))

    compiled = empty_session.execute.call_args[0][0].compile()
    sql = str(compiled).lower()
    params = compiled.params

    assert "filter" in sql
    assert "access_level in" in sql
    # status filter
    assert "status" in sql
    # access_level expanding bind list
    bind_param = next(v for k, v in params.items() if k.startswith("access_level_"))
    assert set(bind_param) == {"PUBLIC", "LOGGED"}
    # status param
    assert any(v == "PUBLISHED" for v in params.values())


@pytest.mark.asyncio
async def test_list_tree_sql_uses_left_outer_join(empty_session: Any) -> None:
    repo = CategoryRepository(empty_session)
    await repo.list_tree(frozenset({AccessLevel.PUBLIC}))
    sql = str(empty_session.execute.call_args[0][0].compile()).lower()
    assert "left outer join" in sql or "left join" in sql
    assert "articles.category = categories.slug" in sql


@pytest.mark.asyncio
async def test_list_tree_sql_groups_by_category_id(empty_session: Any) -> None:
    repo = CategoryRepository(empty_session)
    await repo.list_tree(frozenset({AccessLevel.PUBLIC}))
    sql = str(empty_session.execute.call_args[0][0].compile()).lower()
    assert "group by categories.id" in sql


@pytest.mark.asyncio
async def test_list_tree_empty_access_levels_still_runs_sql(
    empty_session: Any,
) -> None:
    """Сознательное отличие от tags: дерево возвращается даже при empty
    scope (структура полезна для UX), но article_count будет 0."""
    repo = CategoryRepository(empty_session)
    result = await repo.list_tree(frozenset())
    assert result == []
    empty_session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Tree-build logic


@pytest.mark.asyncio
async def test_tree_build_flat_roots() -> None:
    """3 roots без parent_id → flat list."""
    rows = [_make_row("a"), _make_row("b"), _make_row("c")]
    session = _session_returning(rows)
    repo = CategoryRepository(session)
    result = await repo.list_tree(frozenset({AccessLevel.PUBLIC}))
    assert len(result) == 3
    assert {n.slug for n in result} == {"a", "b", "c"}
    assert all(n.children == [] for n in result)


@pytest.mark.asyncio
async def test_tree_build_nested_two_levels() -> None:
    """Root → 2 children → grandchild."""
    root = _make_row("root")
    child_a = _make_row("child-a", parent_id=root.id)
    child_b = _make_row("child-b", parent_id=root.id)
    grandchild = _make_row("grandchild", parent_id=child_a.id)
    rows = [root, child_a, child_b, grandchild]
    session = _session_returning(rows)
    repo = CategoryRepository(session)
    result = await repo.list_tree(frozenset({AccessLevel.PUBLIC}))
    assert len(result) == 1
    r = result[0]
    assert r.slug == "root"
    assert len(r.children) == 2
    a, b = r.children
    # Сортировка: equal article_count=0 → slug ASC
    assert a.slug == "child-a"
    assert b.slug == "child-b"
    assert len(a.children) == 1
    assert a.children[0].slug == "grandchild"


@pytest.mark.asyncio
async def test_tree_build_three_levels() -> None:
    """4-уровневая вложенность (root → l1 → l2 → l3)."""
    root = _make_row("l0")
    l1 = _make_row("l1", parent_id=root.id)
    l2 = _make_row("l2", parent_id=l1.id)
    l3 = _make_row("l3", parent_id=l2.id)
    session = _session_returning([root, l1, l2, l3])
    repo = CategoryRepository(session)
    result = await repo.list_tree(frozenset({AccessLevel.PUBLIC}))
    assert result[0].slug == "l0"
    assert result[0].children[0].slug == "l1"
    assert result[0].children[0].children[0].slug == "l2"
    assert result[0].children[0].children[0].children[0].slug == "l3"


@pytest.mark.asyncio
async def test_tree_build_orphan_node_becomes_root() -> None:
    """parent_id указывает на UUID, которого нет в результатах → node
    добавляется в roots (защита от corrupted FK)."""
    ghost_parent = uuid4()
    orphan = _make_row("orphan", parent_id=ghost_parent)
    session = _session_returning([orphan])
    repo = CategoryRepository(session)
    result = await repo.list_tree(frozenset({AccessLevel.PUBLIC}))
    assert len(result) == 1
    assert result[0].slug == "orphan"


# ---------------------------------------------------------------------------
# Sorting


@pytest.mark.asyncio
async def test_sort_by_article_count_desc_then_slug_asc() -> None:
    """Roots: a(3), b(5), c(5), d(1) → b, c, a, d (count DESC, slug ASC при tie)."""
    rows = [
        _make_row("a", article_count=3),
        _make_row("b", article_count=5),
        _make_row("c", article_count=5),
        _make_row("d", article_count=1),
    ]
    session = _session_returning(rows)
    repo = CategoryRepository(session)
    result = await repo.list_tree(frozenset({AccessLevel.PUBLIC}))
    slugs = [n.slug for n in result]
    assert slugs == ["b", "c", "a", "d"]


def test_sort_recursive_applies_to_children() -> None:
    """_sort_recursive сортирует и каждый child-список."""
    root = CategoryNode(
        id=uuid4(),
        slug="r",
        title="R",
        description=None,
        parent_id=None,
        article_count=0,
        children=[
            CategoryNode(uuid4(), "z", "Z", None, None, 1),
            CategoryNode(uuid4(), "a", "A", None, None, 5),
        ],
    )
    _sort_recursive([root])
    assert [c.slug for c in root.children] == ["a", "z"]
