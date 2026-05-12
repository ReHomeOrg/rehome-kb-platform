"""Integration: end-to-end GET /api/v1/tags с реальным Postgres.

Эти тесты:
1. Создают articles напрямую через asyncpg (без HTTP) с разными tags,
   access_level, status — фикстура `seed_tagged`.
2. Дёргают backend uvicorn через kb_client с/без m2m JWT.
3. Проверяют:
   - ADR-0003 storage-level фильтр (guest видит только PUBLIC tags),
   - q-фильтр (ILIKE substring, case-insensitive),
   - сортировку (count DESC, name ASC),
   - limit clamp.
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
async def seed_tagged(db: asyncpg.Connection) -> AsyncIterator[str]:
    """Создаёт articles с разными tags для проверки агрегации.

    Возвращает фиксированный suffix чтобы slug'и оставались уникальными
    при параллельных прогонах CI.
    """
    suffix = uuid4().hex[:8]
    rows = [
        # (slug, status, access_level, tags)
        (f"pub-a-{suffix}", "PUBLISHED", "PUBLIC", ["договор", "аренда"]),
        (f"pub-b-{suffix}", "PUBLISHED", "PUBLIC", ["договор"]),
        (f"pub-c-{suffix}", "PUBLISHED", "PUBLIC", ["аренда"]),
        # STAFF tag «секретный» НЕ должен быть виден guest'у
        (f"staff-{suffix}", "PUBLISHED", "STAFF", ["договор", "секретный"]),
        # DRAFT не учитывается даже если PUBLIC
        (f"draft-{suffix}", "DRAFT", "PUBLIC", ["договор", "черновик"]),
    ]
    for slug, status, level, tags in rows:
        import json

        await db.execute(
            """
            INSERT INTO articles
                (slug, title, body_markdown, audience, category, access_level,
                 status, tags)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
            """,
            slug,
            f"Title {slug}",
            "Body",
            "all",
            "test",
            level,
            status,
            json.dumps(tags),
        )

    yield suffix

    for slug, *_ in rows:
        await db.execute("DELETE FROM articles WHERE slug = $1", slug)


@pytest.mark.integration
def test_anonymous_gets_only_public_tags(kb_client: httpx.Client, seed_tagged: str) -> None:
    """Guest без JWT: только теги из PUBLIC PUBLISHED статей.

    Ожидаем: договор (2), аренда (2). НЕ ожидаем: секретный, черновик.
    """
    response = kb_client.get("/api/v1/tags")
    assert response.status_code == 200, response.text
    body = response.json()
    names = {item["name"] for item in body["data"]}
    assert "договор" in names
    assert "аренда" in names
    assert "секретный" not in names, "STAFF tag leaked to guest"
    assert "черновик" not in names, "DRAFT tag leaked"


@pytest.mark.integration
def test_anonymous_q_filter_substring(kb_client: httpx.Client, seed_tagged: str) -> None:
    """q='аренд' матчит 'аренда' (case-insensitive substring)."""
    response = kb_client.get("/api/v1/tags", params={"q": "аренд"})
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["data"]}
    assert "аренда" in names
    assert "договор" not in names


@pytest.mark.integration
def test_anonymous_sort_count_desc_then_name_asc(kb_client: httpx.Client, seed_tagged: str) -> None:
    """`договор` (count=2) и `аренда` (count=2) — равный count, sort by name ASC.

    В алфавите кириллицы 'а' < 'д', значит аренда идёт раньше.
    """
    response = kb_client.get("/api/v1/tags")
    data = response.json()["data"]
    # Берём только наши seed-теги (другие могут быть в БД от смежных тестов)
    relevant = [t for t in data if t["name"] in {"договор", "аренда"}]
    # Оба должны иметь count=2; при равенстве — name ASC
    assert all(t["article_count"] == 2 for t in relevant)
    names_in_order = [t["name"] for t in relevant]
    assert names_in_order == sorted(names_in_order)


@pytest.mark.integration
def test_m2m_token_sees_staff_tags(
    kb_client: httpx.Client, seed_tagged: str, m2m_token: str
) -> None:
    """m2m токен (с расширенным scope) → STAFF-теги видны."""
    response = kb_client.get(
        "/api/v1/tags",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200, response.text
    names = {item["name"] for item in response.json()["data"]}
    assert "секретный" in names, "m2m token не получает STAFF теги"


@pytest.mark.integration
def test_limit_clamps_results(kb_client: httpx.Client, seed_tagged: str) -> None:
    response = kb_client.get("/api/v1/tags", params={"limit": 1})
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data) == 1


@pytest.mark.integration
def test_q_with_user_wildcard_does_not_match_all(kb_client: httpx.Client, seed_tagged: str) -> None:
    """`q='%'` НЕ должно стать match-all: `%` экранируется на стороне БД."""
    response = kb_client.get("/api/v1/tags", params={"q": "%"})
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["data"]}
    # Никаких реальных тегов с literal `%` в seed нет → ответ должен быть пуст
    # (или содержать только теги, имеющие literal `%`).
    assert "договор" not in names
    assert "аренда" not in names
