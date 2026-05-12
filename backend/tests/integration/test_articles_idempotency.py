"""Integration: end-to-end Idempotency-Key для POST /articles (E5.1 #44)."""

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
async def db_cleanup() -> AsyncIterator[list[str]]:
    created: list[str] = []
    yield created
    conn = await asyncpg.connect(RAW_DSN)
    try:
        for slug in created:
            await conn.execute("DELETE FROM articles WHERE slug = $1", slug)
        # Cleanup any idempotency_keys created during tests.
        await conn.execute("DELETE FROM idempotency_keys WHERE request_path = '/api/v1/articles'")
    finally:
        await conn.close()


def _payload(slug: str) -> dict[str, str]:
    return {
        "slug": slug,
        "title": f"Test {slug}",
        "body_markdown": "# Content",
        "category": "guide",
        "audience": "tenant",
        "access_level": "PUBLIC",
        "status": "PUBLISHED",
    }


@pytest.mark.integration
def test_post_with_idempotency_key_retry_returns_same_response(
    kb_client: httpx.Client,
    m2m_token: str,
    db_cleanup: list[str],
) -> None:
    """Первый POST создаёт; retry того же body + key → cached response,
    в БД ровно 1 статья."""
    slug = f"e51-retry-{uuid4().hex[:8]}"
    db_cleanup.append(slug)
    key = str(uuid4())
    auth = {
        "Authorization": f"Bearer {m2m_token}",
        "Idempotency-Key": key,
        "Content-Type": "application/json",
    }
    body = json.dumps(_payload(slug)).encode()

    first = kb_client.post("/api/v1/articles", headers=auth, content=body)
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    # Retry с теми же bytes.
    second = kb_client.post("/api/v1/articles", headers=auth, content=body)
    assert second.status_code == 201, second.text
    # Replay → ровно тот же response.
    assert second.json()["id"] == first_id


@pytest.mark.integration
def test_post_with_idempotency_key_different_body_returns_409(
    kb_client: httpx.Client,
    m2m_token: str,
    db_cleanup: list[str],
) -> None:
    """Same key, different body → 409."""
    slug = f"e51-conflict-{uuid4().hex[:8]}"
    db_cleanup.append(slug)
    key = str(uuid4())
    auth = {
        "Authorization": f"Bearer {m2m_token}",
        "Idempotency-Key": key,
    }
    first = kb_client.post("/api/v1/articles", headers=auth, json=_payload(slug))
    assert first.status_code == 201

    # Different body — отличающийся title.
    different_body = _payload(slug)
    different_body["title"] = "Different title"
    conflict = kb_client.post("/api/v1/articles", headers=auth, json=different_body)
    assert conflict.status_code == 409


@pytest.mark.integration
def test_post_with_invalid_idempotency_key_returns_422(
    kb_client: httpx.Client, m2m_token: str
) -> None:
    response = kb_client.post(
        "/api/v1/articles",
        headers={
            "Authorization": f"Bearer {m2m_token}",
            "Idempotency-Key": "not-a-uuid",
        },
        json=_payload(f"e51-bad-{uuid4().hex[:8]}"),
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_post_without_idempotency_key_creates_each_time(
    kb_client: httpx.Client,
    m2m_token: str,
    db_cleanup: list[str],
) -> None:
    """Без header — legacy behavior; idempotency не активен."""
    auth = {"Authorization": f"Bearer {m2m_token}"}

    slug1 = f"e51-noidem-1-{uuid4().hex[:8]}"
    slug2 = f"e51-noidem-2-{uuid4().hex[:8]}"
    db_cleanup.append(slug1)
    db_cleanup.append(slug2)

    r1 = kb_client.post("/api/v1/articles", headers=auth, json=_payload(slug1))
    r2 = kb_client.post("/api/v1/articles", headers=auth, json=_payload(slug2))
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]
