"""Integration: end-to-end GET /api/v1/articles c реальным Postgres + JWT.

Реализует security-тесты для list endpoint (E2.2 / Issue #25):
- Anonymous видит только PUBLIC + PUBLISHED.
- staff_admin видит STAFF, не HR_RESTRICTED (ADR-0003 critical).
- DRAFT не отдаётся даже staff_admin.
- Cursor-пагинация: full chunks + last chunk + has_more flag.
- Filter by category — отсекает не-matching строки.

DATABASE_URL и backend uvicorn запущены CI-job'ом 'Integration (Keycloak)'.
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
async def seed_mixed_visibility(
    db: asyncpg.Connection,
) -> AsyncIterator[dict[str, str]]:
    """5 статей разных видимостей: PUBLIC/STAFF/HR_RESTRICTED × PUBLISHED/DRAFT."""
    seeded: dict[str, str] = {}
    rows = [
        ("public_pub_1", "PUBLISHED", "PUBLIC", "guide"),
        ("public_pub_2", "PUBLISHED", "PUBLIC", "faq"),
        ("staff_pub", "PUBLISHED", "STAFF", "regulation"),
        ("hr_pub", "PUBLISHED", "HR_RESTRICTED", "policy"),
        ("public_draft", "DRAFT", "PUBLIC", "guide"),
    ]
    for key, status, level, category in rows:
        slug = f"e22-{key}-{uuid4().hex[:8]}"
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
            category,
            level,
            status,
        )
        seeded[key] = slug

    yield seeded

    for slug in seeded.values():
        await db.execute("DELETE FROM articles WHERE slug = $1", slug)


def _slugs(body: dict) -> set[str]:  # type: ignore[type-arg]
    return {item["slug"] for item in body["data"]}


@pytest.mark.integration
@pytest.mark.security
def test_anonymous_list_sees_only_public_published(
    kb_client: httpx.Client, seed_mixed_visibility: dict[str, str]
) -> None:
    response = kb_client.get("/api/v1/articles?limit=100")
    assert response.status_code == 200, response.text
    slugs = _slugs(response.json())
    seeded = seed_mixed_visibility
    # Видит обе PUBLIC published.
    assert seeded["public_pub_1"] in slugs
    assert seeded["public_pub_2"] in slugs
    # НЕ видит STAFF / HR / DRAFT.
    assert seeded["staff_pub"] not in slugs
    assert seeded["hr_pub"] not in slugs
    assert seeded["public_draft"] not in slugs


@pytest.mark.integration
@pytest.mark.security
def test_staff_admin_list_sees_staff_but_not_hr(
    kb_client: httpx.Client,
    m2m_token: str,
    seed_mixed_visibility: dict[str, str],
) -> None:
    """ADR-0003 critical: staff_admin scope БЕЗ HR_RESTRICTED."""
    response = kb_client.get(
        "/api/v1/articles?limit=100",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200, response.text
    slugs = _slugs(response.json())
    seeded = seed_mixed_visibility
    assert seeded["staff_pub"] in slugs
    assert seeded["public_pub_1"] in slugs
    # HR_RESTRICTED недоступен staff_admin.
    assert seeded["hr_pub"] not in slugs
    # DRAFT не отдаётся даже авторизованному.
    assert seeded["public_draft"] not in slugs


@pytest.mark.integration
@pytest.mark.security
def test_list_drafts_never_returned(
    kb_client: httpx.Client,
    m2m_token: str,
    seed_mixed_visibility: dict[str, str],
) -> None:
    response = kb_client.get(
        "/api/v1/articles?limit=100",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    slugs = _slugs(response.json())
    assert seed_mixed_visibility["public_draft"] not in slugs


@pytest.mark.integration
def test_list_category_filter(
    kb_client: httpx.Client, seed_mixed_visibility: dict[str, str]
) -> None:
    """category=guide → только статьи этой категории."""
    response = kb_client.get("/api/v1/articles?category=guide&limit=100")
    assert response.status_code == 200
    slugs = _slugs(response.json())
    # public_pub_1 — guide PUBLIC published, должен попасть.
    assert seed_mixed_visibility["public_pub_1"] in slugs
    # public_pub_2 — faq, должен НЕ попасть.
    assert seed_mixed_visibility["public_pub_2"] not in slugs


@pytest.fixture
async def seed_pagination_articles(
    db: asyncpg.Connection,
) -> AsyncIterator[list[str]]:
    """5 PUBLIC PUBLISHED articles в категории `pagi` — для пагинации."""
    seeded: list[str] = []
    for i in range(5):
        slug = f"e22-pagi-{i}-{uuid4().hex[:8]}"
        await db.execute(
            """
            INSERT INTO articles
                (slug, title, body_markdown, audience, category, access_level, status)
            VALUES ($1, $2, 'b', 'all', 'pagi', 'PUBLIC', 'PUBLISHED')
            """,
            slug,
            f"Pagi {i}",
        )
        seeded.append(slug)
    yield seeded
    for slug in seeded:
        await db.execute("DELETE FROM articles WHERE slug = $1", slug)


@pytest.mark.integration
def test_list_pagination_cursor_flow(
    kb_client: httpx.Client, seed_pagination_articles: list[str]
) -> None:
    """Постранично проходим через 5 статей с limit=2 (3 страницы)."""
    all_seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):  # защита от бесконечного цикла
        url = "/api/v1/articles?category=pagi&limit=2"
        if cursor:
            url += f"&cursor={cursor}"
        response = kb_client.get(url)
        assert response.status_code == 200, response.text
        body = response.json()
        page_slugs = [item["slug"] for item in body["data"]]
        all_seen.extend(page_slugs)
        if not body["pagination"]["has_more"]:
            break
        cursor = body["pagination"]["cursor_next"]
        assert cursor is not None
    # Все 5 наших статей собраны без дубликатов.
    assert set(all_seen) == set(seed_pagination_articles)
    assert len(all_seen) == 5


@pytest.mark.integration
def test_list_invalid_cursor_returns_400(kb_client: httpx.Client) -> None:
    response = kb_client.get("/api/v1/articles?cursor=это-не-base64-©")
    assert response.status_code == 400


# ============================================================
# tags filter (E2.4)
# ============================================================


@pytest.fixture
async def seed_tagged_articles(
    db: asyncpg.Connection,
) -> AsyncIterator[dict[str, str]]:
    """Статьи с разными tags для проверки фильтра."""
    seeded: dict[str, str] = {}
    rows = [
        # (key, slug, tags)
        ("dogovor_naimatel", "договор + наниматель", '["договор", "наниматель"]'),
        ("dogovor_landlord", "договор + landlord", '["договор", "landlord"]'),
        ("only_dogovor", "только договор", '["договор"]'),
        ("no_match", "другие теги", '["payments", "fee"]'),
    ]
    for key, title, tags_json in rows:
        slug = f"e24-{key}-{uuid4().hex[:8]}"
        await db.execute(
            """
            INSERT INTO articles
                (slug, title, body_markdown, audience, category, access_level,
                 status, tags)
            VALUES ($1, $2, 'b', 'all', 'guide', 'PUBLIC', 'PUBLISHED', $3::jsonb)
            """,
            slug,
            title,
            tags_json,
        )
        seeded[key] = slug
    yield seeded
    for slug in seeded.values():
        await db.execute("DELETE FROM articles WHERE slug = $1", slug)


@pytest.mark.integration
def test_list_filter_by_single_tag(
    kb_client: httpx.Client, seed_tagged_articles: dict[str, str]
) -> None:
    """`?tags=договор` → статьи с тегом договор (3 из 4)."""
    response = kb_client.get("/api/v1/articles?tags=договор&limit=100")
    assert response.status_code == 200
    slugs = _slugs(response.json())
    assert seed_tagged_articles["dogovor_naimatel"] in slugs
    assert seed_tagged_articles["dogovor_landlord"] in slugs
    assert seed_tagged_articles["only_dogovor"] in slugs
    assert seed_tagged_articles["no_match"] not in slugs


@pytest.mark.integration
def test_list_filter_by_multiple_tags_and_semantics(
    kb_client: httpx.Client, seed_tagged_articles: dict[str, str]
) -> None:
    """`?tags=договор,наниматель` → статья ДОЛЖНА иметь оба тега (AND)."""
    response = kb_client.get("/api/v1/articles?tags=договор,наниматель&limit=100")
    assert response.status_code == 200
    slugs = _slugs(response.json())
    # Только статья с обоими тегами.
    assert seed_tagged_articles["dogovor_naimatel"] in slugs
    assert seed_tagged_articles["dogovor_landlord"] not in slugs
    assert seed_tagged_articles["only_dogovor"] not in slugs


@pytest.mark.integration
def test_list_filter_by_nonexistent_tag_returns_empty(
    kb_client: httpx.Client, seed_tagged_articles: dict[str, str]
) -> None:
    response = kb_client.get("/api/v1/articles?tags=nonexistent-tag-xyz&limit=100")
    assert response.status_code == 200
    slugs = _slugs(response.json())
    for slug in seed_tagged_articles.values():
        assert slug not in slugs


@pytest.mark.integration
def test_list_filter_tags_too_many_returns_422(kb_client: httpx.Client) -> None:
    """>10 тегов → 422."""
    tags = ",".join(f"tag{i}" for i in range(11))
    response = kb_client.get(f"/api/v1/articles?tags={tags}")
    assert response.status_code == 422
