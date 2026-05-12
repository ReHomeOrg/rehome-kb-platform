"""Integration: end-to-end GET /api/v1/articles/{slug} с реальным Postgres + JWT.

Эти тесты:
1. Создают articles напрямую через asyncpg (без HTTP) — фикстура `db_seed`.
2. Дёргают backend uvicorn через kb_client с/без m2m JWT.
3. Проверяют ADR-0003 на storage-level фильтре: DRAFT → 404, scope-out → 404.

Конфигурация:
- DATABASE_URL: postgresql+asyncpg://kb:kb@localhost:5432/rehome_kb (CI env)
- Backend uvicorn запущен с тем же DATABASE_URL.
"""

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest

# asyncpg DSN (без +asyncpg префикса SQLAlchemy)
RAW_DSN = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://kb:kb@localhost:5432/rehome_kb"
).replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def db() -> AsyncIterator[asyncpg.Connection]:
    """Прямой asyncpg connection — для seed/cleanup без HTTP."""
    conn = await asyncpg.connect(RAW_DSN)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def seed_articles(db: asyncpg.Connection) -> AsyncIterator[dict[str, str]]:
    """Создаёт 4 статьи разных видимостей, возвращает {ключ → slug}."""
    seeded: dict[str, str] = {}

    rows = [
        # (key, slug, status, access_level)
        ("public_published", f"public-published-{uuid4().hex[:8]}", "PUBLISHED", "PUBLIC"),
        ("staff_published", f"staff-published-{uuid4().hex[:8]}", "PUBLISHED", "STAFF"),
        ("public_draft", f"public-draft-{uuid4().hex[:8]}", "DRAFT", "PUBLIC"),
        ("hr_published", f"hr-published-{uuid4().hex[:8]}", "PUBLISHED", "HR_RESTRICTED"),
    ]

    for key, slug, status, level in rows:
        await db.execute(
            """
            INSERT INTO articles
                (slug, title, body_markdown, audience, category, access_level, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            slug,
            f"Title {key}",
            "Body markdown",
            "all",
            "test",
            level,
            status,
        )
        seeded[key] = slug

    yield seeded

    # Cleanup.
    for slug in seeded.values():
        await db.execute("DELETE FROM articles WHERE slug = $1", slug)


@pytest.mark.integration
def test_anonymous_can_read_public_published(
    kb_client: httpx.Client, seed_articles: dict[str, str]
) -> None:
    response = kb_client.get(f"/api/v1/articles/{seed_articles['public_published']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slug"] == seed_articles["public_published"]
    assert body["status"] == "PUBLISHED"


@pytest.mark.integration
@pytest.mark.security
def test_anonymous_cannot_see_staff_published(
    kb_client: httpx.Client, seed_articles: dict[str, str]
) -> None:
    """ADR-0003 masking: гость не должен получить 403, только 404."""
    response = kb_client.get(f"/api/v1/articles/{seed_articles['staff_published']}")
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.security
def test_draft_returns_404_even_for_authorized(
    kb_client: httpx.Client, m2m_token: str, seed_articles: dict[str, str]
) -> None:
    """DRAFT не отдаётся никому — даже staff_admin (S4 review note)."""
    response = kb_client.get(
        f"/api/v1/articles/{seed_articles['public_draft']}",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.security
def test_staff_admin_cannot_see_hr_restricted(
    kb_client: httpx.Client, m2m_token: str, seed_articles: dict[str, str]
) -> None:
    """ADR-0003 critical: staff_admin scope НЕ имеет HR_RESTRICTED level → 404."""
    response = kb_client.get(
        f"/api/v1/articles/{seed_articles['hr_published']}",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 404
