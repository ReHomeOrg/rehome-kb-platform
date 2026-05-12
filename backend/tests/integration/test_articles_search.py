"""Integration: end-to-end Postgres FTS search (E2.5a #46)."""

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
async def seed_search_articles(
    db: asyncpg.Connection,
) -> AsyncIterator[dict[str, str]]:
    """Seed статей для разных search-сценариев.

    Все PUBLIC PUBLISHED — anonymous-видимые.
    """
    seeded: dict[str, str] = {}
    rows = [
        # (key, title, body, access_level, status)
        (
            "dogovor_arendy",
            "Договор аренды квартиры",
            "Как подписать договор аренды и какие договоры бывают",
            "PUBLIC",
            "PUBLISHED",
        ),
        (
            "nanimatel",
            "Права нанимателя",
            "Наниматель имеет право на...",
            "PUBLIC",
            "PUBLISHED",
        ),
        (
            "staff_only",
            "Внутренний регламент",
            "Договоры с агентами обрабатываются...",
            "STAFF",
            "PUBLISHED",
        ),
        (
            "draft_public",
            "Черновик про договоры",
            "Договор будет опубликован позже",
            "PUBLIC",
            "DRAFT",
        ),
    ]
    for key, title, body, access_level, status in rows:
        slug = f"e25-{key}-{uuid4().hex[:8]}"
        await db.execute(
            """
            INSERT INTO articles
                (slug, title, body_markdown, audience, category, access_level, status)
            VALUES ($1, $2, $3, 'all', 'guide', $4, $5)
            """,
            slug,
            title,
            body,
            access_level,
            status,
        )
        seeded[key] = slug
    yield seeded
    for slug in seeded.values():
        await db.execute("DELETE FROM articles WHERE slug = $1", slug)


def _slugs_from_titles(
    body: dict,  # type: ignore[type-arg]
    seeded: dict[str, str],
) -> set[str]:
    """Маппинг title → seeded slug (для проверки what's found)."""
    title_to_key = {
        "Договор аренды квартиры": "dogovor_arendy",
        "Права нанимателя": "nanimatel",
        "Внутренний регламент": "staff_only",
        "Черновик про договоры": "draft_public",
    }
    found = set()
    for hit in body["data"]:
        key = title_to_key.get(hit["title"])
        if key and key in seeded:
            found.add(seeded[key])
    return found


@pytest.mark.integration
def test_search_finds_by_title(
    kb_client: httpx.Client, seed_search_articles: dict[str, str]
) -> None:
    """`q=аренды` находит статью с этим словом в title."""
    response = kb_client.post("/api/v1/articles/search", json={"q": "аренды"})
    assert response.status_code == 200, response.text
    found = _slugs_from_titles(response.json(), seed_search_articles)
    assert seed_search_articles["dogovor_arendy"] in found


@pytest.mark.integration
def test_search_russian_stemming(
    kb_client: httpx.Client, seed_search_articles: dict[str, str]
) -> None:
    """Russian stemming: `q=договор` находит «договоры» в body."""
    response = kb_client.post("/api/v1/articles/search", json={"q": "договор"})
    assert response.status_code == 200, response.text
    found = _slugs_from_titles(response.json(), seed_search_articles)
    # Статьи с «договор» / «договоры» — обе должны найтись.
    assert seed_search_articles["dogovor_arendy"] in found


@pytest.mark.integration
def test_search_snippet_contains_highlight(
    kb_client: httpx.Client, seed_search_articles: dict[str, str]
) -> None:
    response = kb_client.post("/api/v1/articles/search", json={"q": "аренды"})
    body = response.json()
    # Хотя бы один hit имеет snippet с `<b>...</b>`.
    has_highlight = any(hit["snippet"] and "<b>" in hit["snippet"] for hit in body["data"])
    assert has_highlight


@pytest.mark.integration
@pytest.mark.security
def test_search_drafts_excluded_from_anonymous(
    kb_client: httpx.Client, seed_search_articles: dict[str, str]
) -> None:
    """ADR-0003 read-mask: DRAFT не в результатах даже если содержит query."""
    response = kb_client.post("/api/v1/articles/search", json={"q": "договор"})
    found = _slugs_from_titles(response.json(), seed_search_articles)
    assert seed_search_articles["draft_public"] not in found


@pytest.mark.integration
@pytest.mark.security
def test_search_staff_articles_hidden_from_anonymous(
    kb_client: httpx.Client, seed_search_articles: dict[str, str]
) -> None:
    """ADR-0003: anonymous (only PUBLIC) не видит STAFF article в search."""
    response = kb_client.post("/api/v1/articles/search", json={"q": "договоры"})
    found = _slugs_from_titles(response.json(), seed_search_articles)
    assert seed_search_articles["staff_only"] not in found


@pytest.mark.integration
@pytest.mark.security
def test_search_staff_admin_sees_staff_articles(
    kb_client: httpx.Client,
    m2m_token: str,
    seed_search_articles: dict[str, str],
) -> None:
    """staff_admin scope видит STAFF article."""
    response = kb_client.post(
        "/api/v1/articles/search",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json={"q": "договоры"},
    )
    found = _slugs_from_titles(response.json(), seed_search_articles)
    assert seed_search_articles["staff_only"] in found


@pytest.mark.integration
def test_search_score_descending_order(
    kb_client: httpx.Client, seed_search_articles: dict[str, str]
) -> None:
    response = kb_client.post("/api/v1/articles/search", json={"q": "договор"})
    body = response.json()
    if len(body["data"]) >= 2:
        scores = [hit["score"] for hit in body["data"]]
        assert scores == sorted(scores, reverse=True)


@pytest.mark.integration
def test_search_empty_q_returns_422(kb_client: httpx.Client) -> None:
    response = kb_client.post("/api/v1/articles/search", json={"q": ""})
    assert response.status_code == 422


@pytest.mark.integration
def test_search_no_matches_returns_empty(kb_client: httpx.Client) -> None:
    response = kb_client.post("/api/v1/articles/search", json={"q": "abracadabra-no-such-word"})
    assert response.status_code == 200
    assert response.json()["data"] == []
