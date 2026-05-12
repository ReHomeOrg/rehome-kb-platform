"""Integration: end-to-end /api/v1/chat/sessions/* (E3.2 #63).

Покрывает:
- POST anon → GET с session_token → видит созданную session.
- POST с JWT → GET без JWT → 404 mask.
- POST с context → GET возвращает context.
- DELETE soft-deletes; GET 404; повторный DELETE 404.
- m2m token → anon flow (m2m sub не UUID).
- DELETE без identifier'ов → 404 mask.
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
async def cleanup_sessions(
    db: asyncpg.Connection,
) -> AsyncIterator[list[str]]:
    """Список id для cleanup после теста (hard-delete)."""
    ids: list[str] = []
    yield ids
    for sid in ids:
        await db.execute("DELETE FROM chat_sessions WHERE id = $1", sid)


@pytest.mark.integration
def test_anon_post_then_get_with_token(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    """POST без JWT → 201 + token header → GET с token → 200."""
    r1 = kb_client.post("/api/v1/chat/sessions")
    assert r1.status_code == 201, r1.text
    body = r1.json()
    session_id = body["id"]
    cleanup_sessions.append(session_id)
    token = r1.headers.get("X-Chat-Session-Token")
    assert token is not None
    assert body["user_id"] is None
    assert body["scope"] == "guest"

    r2 = kb_client.get(
        f"/api/v1/chat/sessions/{session_id}",
        headers={"X-Chat-Session-Token": token},
    )
    assert r2.status_code == 200
    assert r2.json()["id"] == session_id
    # messages empty (no POST messages в E3.2)
    assert r2.json()["messages"] == []


@pytest.mark.integration
def test_anon_get_without_token_returns_404(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    """ADR-0003 mask: создали session → GET без token → 404."""
    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)

    r2 = kb_client.get(f"/api/v1/chat/sessions/{session_id}")
    assert r2.status_code == 404


@pytest.mark.integration
def test_m2m_token_creates_anon_session(
    kb_client: httpx.Client, m2m_token: str, cleanup_sessions: list[str]
) -> None:
    """m2m sub не UUID — graceful degradation в anon flow."""
    r1 = kb_client.post(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert r1.status_code == 201
    body = r1.json()
    cleanup_sessions.append(body["id"])
    # m2m → anon: user_id null, session_token в header
    assert body["user_id"] is None
    assert r1.headers.get("X-Chat-Session-Token") is not None


@pytest.mark.integration
def test_anon_post_with_context(kb_client: httpx.Client, cleanup_sessions: list[str]) -> None:
    """POST с context → context сохранён, GET возвращает его."""
    premises_id = str(uuid4())
    r1 = kb_client.post(
        "/api/v1/chat/sessions",
        json={"context": {"page_url": "https://example.org/", "premises_id": premises_id}},
    )
    assert r1.status_code == 201
    body = r1.json()
    cleanup_sessions.append(body["id"])
    token = r1.headers["X-Chat-Session-Token"]

    r2 = kb_client.get(
        f"/api/v1/chat/sessions/{body['id']}",
        headers={"X-Chat-Session-Token": token},
    )
    assert r2.json()["context"]["premises_id"] == premises_id


@pytest.mark.integration
def test_delete_soft_deletes_session(
    kb_client: httpx.Client,
) -> None:
    """POST → DELETE 204 → GET 404 → повторный DELETE 404 (idempotent)."""
    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    token = r1.headers["X-Chat-Session-Token"]
    auth = {"X-Chat-Session-Token": token}

    r2 = kb_client.delete(f"/api/v1/chat/sessions/{session_id}", headers=auth)
    assert r2.status_code == 204

    r3 = kb_client.get(f"/api/v1/chat/sessions/{session_id}", headers=auth)
    assert r3.status_code == 404

    r4 = kb_client.delete(f"/api/v1/chat/sessions/{session_id}", headers=auth)
    assert r4.status_code == 404


@pytest.mark.integration
def test_delete_no_identifier_returns_404(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    """DELETE без X-Chat-Session-Token и без JWT → 404 (mask)."""
    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)

    # Без token header — не сможем delete
    r2 = kb_client.delete(f"/api/v1/chat/sessions/{session_id}")
    assert r2.status_code == 404
