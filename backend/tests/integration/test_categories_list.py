"""Integration: end-to-end GET /api/v1/categories с реальным Postgres.

Эти тесты:
1. Создают categories напрямую через asyncpg (без HTTP), с self-referential
   parent_id (иерархия).
2. Создают articles с разными access_level/status, привязанные через
   articles.category = categories.slug.
3. Дёргают backend uvicorn через kb_client с/без m2m JWT.
4. Проверяют:
   - tree-build (root → children),
   - ADR-0003 (guest НЕ видит STAFF article_count),
   - article_count учитывает только PUBLISHED + access_level.
"""

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest

RAW_DSN = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://kb:kb@localhost:5432/rehome_kb"
).replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def db() -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(RAW_DSN)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def seed_tree(db: asyncpg.Connection) -> AsyncIterator[dict[str, str]]:
    """Создаёт 1 root + 2 child categories, 4 articles с разными access_level.

    Возвращает {category_slug → slug} для assert'ов.
    """
    suffix = uuid4().hex[:8]
    root_slug = f"root-{suffix}"
    child_a_slug = f"child-a-{suffix}"
    child_b_slug = f"child-b-{suffix}"

    # Создаём root + 2 children с known UUID
    root_id = uuid4()
    child_a_id = uuid4()
    child_b_id = uuid4()
    await db.execute(
        "INSERT INTO categories (id, slug, title) VALUES ($1, $2, $3)",
        root_id,
        root_slug,
        "Root",
    )
    await db.execute(
        "INSERT INTO categories (id, slug, title, parent_id) VALUES ($1, $2, $3, $4)",
        child_a_id,
        child_a_slug,
        "Child A",
        root_id,
    )
    await db.execute(
        "INSERT INTO categories (id, slug, title, parent_id) VALUES ($1, $2, $3, $4)",
        child_b_id,
        child_b_slug,
        "Child B",
        root_id,
    )

    # Articles привязаны к child_a и child_b
    articles = [
        # (slug, status, access_level, category)
        (f"pub-a1-{suffix}", "PUBLISHED", "PUBLIC", child_a_slug),
        (f"pub-a2-{suffix}", "PUBLISHED", "PUBLIC", child_a_slug),
        (f"staff-b1-{suffix}", "PUBLISHED", "STAFF", child_b_slug),
        (f"draft-{suffix}", "DRAFT", "PUBLIC", child_b_slug),
    ]
    for slug, status, level, category in articles:
        await db.execute(
            """
            INSERT INTO articles
                (slug, title, body_markdown, audience, category, access_level, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            slug,
            f"Title {slug}",
            "Body",
            "all",
            category,
            level,
            status,
        )

    yield {
        "root": root_slug,
        "child_a": child_a_slug,
        "child_b": child_b_slug,
    }

    # Cleanup в обратном порядке
    for slug, *_ in articles:
        await db.execute("DELETE FROM articles WHERE slug = $1", slug)
    await db.execute("DELETE FROM categories WHERE id IN ($1, $2)", child_a_id, child_b_id)
    await db.execute("DELETE FROM categories WHERE id = $1", root_id)


def _find_node(nodes: list[dict[str, object]], slug: str) -> dict[str, object] | None:
    for n in nodes:
        if n["slug"] == slug:
            return n
        children = n.get("children")
        if isinstance(children, list):
            sub = _find_node([c for c in children if isinstance(c, dict)], slug)
            if sub is not None:
                return sub
    return None


@pytest.mark.integration
def test_anonymous_sees_tree_structure(kb_client: httpx.Client, seed_tree: dict[str, str]) -> None:
    """Guest без JWT видит дерево + article_count из PUBLIC статей."""
    response = kb_client.get("/api/v1/categories")
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    root = _find_node(data, seed_tree["root"])
    assert root is not None
    children = root.get("children")
    assert isinstance(children, list)

    child_a = _find_node(data, seed_tree["child_a"])
    assert child_a is not None
    # 2 PUBLIC PUBLISHED статьи
    assert child_a["article_count"] == 2

    child_b = _find_node(data, seed_tree["child_b"])
    assert child_b is not None
    # STAFF статья НЕ видна гостю, DRAFT тоже → 0
    assert child_b["article_count"] == 0


@pytest.mark.integration
def test_m2m_token_sees_staff_count(
    kb_client: httpx.Client, seed_tree: dict[str, str], m2m_token: str
) -> None:
    """m2m токен видит STAFF статьи → child_b.article_count >= 1."""
    response = kb_client.get(
        "/api/v1/categories",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    child_b = _find_node(data, seed_tree["child_b"])
    assert child_b is not None
    # STAFF article видна — count=1 (DRAFT всё ещё скрыта)
    assert child_b["article_count"] == 1


@pytest.mark.integration
def test_tree_returns_children_for_root(kb_client: httpx.Client, seed_tree: dict[str, str]) -> None:
    response = kb_client.get("/api/v1/categories")
    data = response.json()["data"]
    root = _find_node(data, seed_tree["root"])
    assert root is not None
    children = root["children"]
    assert isinstance(children, list)
    child_slugs = {c["slug"] for c in children if isinstance(c, dict)}
    assert seed_tree["child_a"] in child_slugs
    assert seed_tree["child_b"] in child_slugs


@pytest.mark.asyncio
@pytest.mark.integration
async def test_check_constraint_blocks_self_reference(db: asyncpg.Connection) -> None:
    """Прямая попытка INSERT с parent_id=id должна упасть на CHECK constraint."""
    bad_id = uuid4()
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await db.execute(
            "INSERT INTO categories (id, slug, title, parent_id) VALUES ($1, $2, $3, $1)",
            bad_id,
            f"self-{bad_id.hex[:6]}",
            "Self",
        )
