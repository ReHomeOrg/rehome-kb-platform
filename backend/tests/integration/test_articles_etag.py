"""Integration: ETag + If-None-Match + If-Match (E5.2 #48)."""

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
async def db_cleanup() -> AsyncIterator[list[str]]:
    created: list[str] = []
    yield created
    conn = await asyncpg.connect(RAW_DSN)
    try:
        for slug in created:
            await conn.execute("DELETE FROM articles WHERE slug = $1", slug)
    finally:
        await conn.close()


def _payload(slug: str, **overrides: str) -> dict[str, str]:
    base = {
        "slug": slug,
        "title": f"T {slug}",
        "body_markdown": "# Content",
        "category": "guide",
        "audience": "tenant",
        "access_level": "PUBLIC",
        "status": "PUBLISHED",
    }
    base.update(overrides)
    return base


@pytest.mark.integration
def test_get_returns_etag_and_vary_authorization(
    kb_client: httpx.Client, m2m_token: str, db_cleanup: list[str]
) -> None:
    slug = f"e52-get-{uuid4().hex[:8]}"
    db_cleanup.append(slug)
    kb_client.post(
        "/api/v1/articles",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug),
    )
    response = kb_client.get(f"/api/v1/articles/{slug}")
    assert response.status_code == 200
    assert response.headers["ETag"].startswith('W/"')
    assert response.headers["Cache-Control"] == "public, max-age=60"
    assert response.headers["Vary"] == "Authorization"


@pytest.mark.integration
def test_get_if_none_match_returns_304(
    kb_client: httpx.Client, m2m_token: str, db_cleanup: list[str]
) -> None:
    """POST → GET (capture ETag) → GET с If-None-Match → 304."""
    slug = f"e52-304-{uuid4().hex[:8]}"
    db_cleanup.append(slug)
    kb_client.post(
        "/api/v1/articles",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug),
    )
    first = kb_client.get(f"/api/v1/articles/{slug}")
    etag = first.headers["ETag"]

    second = kb_client.get(
        f"/api/v1/articles/{slug}",
        headers={"If-None-Match": etag},
    )
    assert second.status_code == 304
    assert second.content == b""
    assert second.headers["ETag"] == etag


@pytest.mark.integration
def test_etag_changes_after_update(
    kb_client: httpx.Client, m2m_token: str, db_cleanup: list[str]
) -> None:
    slug = f"e52-change-{uuid4().hex[:8]}"
    db_cleanup.append(slug)
    auth = {"Authorization": f"Bearer {m2m_token}"}
    kb_client.post("/api/v1/articles", headers=auth, json=_payload(slug))

    first = kb_client.get(f"/api/v1/articles/{slug}")
    etag1 = first.headers["ETag"]

    kb_client.put(
        f"/api/v1/articles/{slug}",
        headers=auth,
        json=_payload(slug, title="Updated"),
    )

    second = kb_client.get(f"/api/v1/articles/{slug}")
    etag2 = second.headers["ETag"]
    assert etag1 != etag2


@pytest.mark.integration
def test_put_if_match_match_returns_200(
    kb_client: httpx.Client, m2m_token: str, db_cleanup: list[str]
) -> None:
    slug = f"e52-match-{uuid4().hex[:8]}"
    db_cleanup.append(slug)
    auth = {"Authorization": f"Bearer {m2m_token}"}
    kb_client.post("/api/v1/articles", headers=auth, json=_payload(slug))

    get_resp = kb_client.get(f"/api/v1/articles/{slug}")
    current_etag = get_resp.headers["ETag"]

    put_resp = kb_client.put(
        f"/api/v1/articles/{slug}",
        headers={**auth, "If-Match": current_etag},
        json=_payload(slug, title="Updated"),
    )
    assert put_resp.status_code == 200


@pytest.mark.integration
def test_put_if_match_mismatch_returns_412(
    kb_client: httpx.Client, m2m_token: str, db_cleanup: list[str]
) -> None:
    slug = f"e52-mismatch-{uuid4().hex[:8]}"
    db_cleanup.append(slug)
    auth = {"Authorization": f"Bearer {m2m_token}"}
    kb_client.post("/api/v1/articles", headers=auth, json=_payload(slug))

    # Stale ETag — точно не совпадает с current.
    put_resp = kb_client.put(
        f"/api/v1/articles/{slug}",
        headers={**auth, "If-Match": 'W/"stale-etag-xxx"'},
        json=_payload(slug, title="Updated"),
    )
    assert put_resp.status_code == 412


@pytest.mark.integration
def test_history_etag_and_cache_headers(
    kb_client: httpx.Client, m2m_token: str, db_cleanup: list[str]
) -> None:
    slug = f"e52-hist-{uuid4().hex[:8]}"
    db_cleanup.append(slug)
    auth = {"Authorization": f"Bearer {m2m_token}"}
    kb_client.post("/api/v1/articles", headers=auth, json=_payload(slug))

    first = kb_client.get(f"/api/v1/articles/{slug}/history")
    assert first.status_code == 200
    assert first.headers["ETag"].startswith('W/"')
    assert first.headers["Vary"] == "Authorization"

    # If-None-Match → 304.
    second = kb_client.get(
        f"/api/v1/articles/{slug}/history",
        headers={"If-None-Match": first.headers["ETag"]},
    )
    assert second.status_code == 304
