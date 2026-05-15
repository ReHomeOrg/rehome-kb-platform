"""Integration: end-to-end GET /api/v1/premises-cards с реальным Postgres.

Покрывает (#194):
- Anonymous catalog list — identification subset only (no PII blocks).
- DRAFT/ARCHIVED невидимы для anon (404).
- Cursor pagination semantics.
- Invalid cursor → 400.
- Slug 404-mask на нелистаемые карточки.
"""

import json
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
async def seed_premises(db: asyncpg.Connection) -> AsyncIterator[dict[str, str]]:
    """Создаёт 3 карточки: PUBLISHED, DRAFT, ARCHIVED."""
    suffix = uuid4().hex[:8]
    published = f"pub-{suffix}"
    draft = f"draft-{suffix}"
    archived = f"arch-{suffix}"

    owner_payload = json.dumps({"name": "Test Owner"})

    rows = [
        (published, "PUBLISHED", None),
        (draft, "DRAFT", None),
        (archived, "ARCHIVED", "now()"),
    ]
    for slug, status, archived_at_sql in rows:
        if archived_at_sql:
            await db.execute(
                """INSERT INTO premises_cards
                   (slug, status, address, owner, archived_at)
                   VALUES ($1, $2, $3, $4::jsonb, now())""",
                slug,
                status,
                f"Test Address {slug}",
                owner_payload,
            )
        else:
            await db.execute(
                """INSERT INTO premises_cards
                   (slug, status, address, owner)
                   VALUES ($1, $2, $3, $4::jsonb)""",
                slug,
                status,
                f"Test Address {slug}",
                owner_payload,
            )

    yield {
        "published": published,
        "draft": draft,
        "archived": archived,
    }

    for slug in (published, draft, archived):
        await db.execute("DELETE FROM premises_cards WHERE slug = $1", slug)


def _slugs_in_list(body: dict[str, object]) -> set[str]:
    data = body["data"]
    assert isinstance(data, list)
    return {item["slug"] for item in data if isinstance(item, dict)}


# ---------------------------------------------------------------------------
# GET /premises — list


@pytest.mark.integration
def test_anon_list_returns_published_only(
    kb_client: httpx.Client, seed_premises: dict[str, str]
) -> None:
    """Catalog visible to anonymous — но только PUBLISHED status."""
    response = kb_client.get("/api/v1/premises-cards", params={"limit": 100})
    assert response.status_code == 200, response.text
    slugs = _slugs_in_list(response.json())
    assert seed_premises["published"] in slugs
    assert seed_premises["draft"] not in slugs, "leaked DRAFT to anon"
    assert seed_premises["archived"] not in slugs, "leaked ARCHIVED to anon"


@pytest.mark.integration
def test_list_response_omits_pii_blocks(
    kb_client: httpx.Client, seed_premises: dict[str, str]
) -> None:
    """List response — identification subset, без owner/financial/tenant_info."""
    response = kb_client.get("/api/v1/premises-cards", params={"limit": 100})
    assert response.status_code == 200
    data = response.json()["data"]
    if data:
        item = data[0]
        # Identification fields присутствуют.
        assert "slug" in item
        assert "address" in item
        # PII blocks НЕ должны быть в list response.
        assert "owner" not in item
        assert "financial_data" not in item
        assert "tenant_info" not in item


@pytest.mark.integration
def test_list_invalid_cursor_returns_400(kb_client: httpx.Client) -> None:
    response = kb_client.get("/api/v1/premises-cards", params={"cursor": "not-base64-cursor"})
    assert response.status_code == 400


@pytest.mark.integration
def test_list_invalid_limit_returns_422(kb_client: httpx.Client) -> None:
    assert kb_client.get("/api/v1/premises-cards", params={"limit": 0}).status_code == 422
    assert kb_client.get("/api/v1/premises-cards", params={"limit": 101}).status_code == 422


@pytest.mark.integration
def test_list_cursor_pagination_works(
    kb_client: httpx.Client, seed_premises: dict[str, str]
) -> None:
    """limit=1 → has_more=true + cursor_next; следующая страница disjoint."""
    first = kb_client.get("/api/v1/premises-cards", params={"limit": 1})
    assert first.status_code == 200
    body1 = first.json()
    if not body1["pagination"]["has_more"]:
        pytest.skip("not enough rows для pagination test")
    cursor = body1["pagination"]["cursor_next"]
    assert isinstance(cursor, str)

    second = kb_client.get("/api/v1/premises-cards", params={"limit": 1, "cursor": cursor})
    assert second.status_code == 200
    body2 = second.json()
    assert _slugs_in_list(body1).isdisjoint(_slugs_in_list(body2))


# ---------------------------------------------------------------------------
# GET /premises/{slug}


@pytest.mark.integration
def test_anon_get_published_returns_200(
    kb_client: httpx.Client, seed_premises: dict[str, str]
) -> None:
    response = kb_client.get(f"/api/v1/premises-cards/{seed_premises['published']}")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == seed_premises["published"]


@pytest.mark.integration
def test_anon_get_draft_returns_404_mask(
    kb_client: httpx.Client, seed_premises: dict[str, str]
) -> None:
    """ADR-0003 404-mask — DRAFT невидим anon'у."""
    response = kb_client.get(f"/api/v1/premises-cards/{seed_premises['draft']}")
    assert response.status_code == 404


@pytest.mark.integration
def test_anon_get_archived_returns_404_mask(
    kb_client: httpx.Client, seed_premises: dict[str, str]
) -> None:
    response = kb_client.get(f"/api/v1/premises-cards/{seed_premises['archived']}")
    assert response.status_code == 404


@pytest.mark.integration
def test_get_invalid_slug_pattern_returns_422(kb_client: httpx.Client) -> None:
    """Slug pattern guard — anti-injection."""
    response = kb_client.get("/api/v1/premises-cards/!!!invalid!!!")
    assert response.status_code == 422
