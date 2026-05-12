"""Integration: POST /api/v1/chat/sessions/{id}/escalate (E3.6 #71).

Покрывает:
- End-to-end: session → escalate → 201 с ticket_id + estimated time.
- Multiple escalations: 2 POST → 2 different ticket_ids в БД.
- CASCADE: hard-delete session → escalations removed.
- Owner mask: escalate без token → 404.
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
async def cleanup_sessions(db: asyncpg.Connection) -> AsyncIterator[list[str]]:
    ids: list[str] = []
    yield ids
    for sid in ids:
        await db.execute("DELETE FROM chat_sessions WHERE id = $1", sid)


@pytest.mark.integration
def test_escalate_e2e_returns_ticket_id_and_estimated_time(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    """POST escalate → 201 c valid ticket_id."""
    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)
    token = r1.headers["X-Chat-Session-Token"]

    r2 = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/escalate",
        json={"reason": "Бот не отвечает", "priority": "high"},
        headers={"X-Chat-Session-Token": token},
    )
    assert r2.status_code == 201, r2.text
    body = r2.json()
    assert "ticket_id" in body
    assert body["estimated_response_time_minutes"] == 10


@pytest.mark.integration
def test_escalate_multiple_creates_different_tickets(
    kb_client: httpx.Client, cleanup_sessions: list[str], db: asyncpg.Connection
) -> None:
    """2 POST на ту же session → 2 разных ticket_id."""
    import asyncio

    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)
    token = r1.headers["X-Chat-Session-Token"]
    auth = {"X-Chat-Session-Token": token}

    r_a = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/escalate",
        json={"priority": "low"},
        headers=auth,
    )
    r_b = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/escalate",
        json={"priority": "normal"},
        headers=auth,
    )
    ticket_a = r_a.json()["ticket_id"]
    ticket_b = r_b.json()["ticket_id"]
    assert ticket_a != ticket_b

    # В БД 2 эскалации привязаны к session
    async def _count() -> int:
        result = await db.fetchval(
            "SELECT count(*) FROM chat_escalations WHERE session_id = $1",
            session_id,
        )
        return int(result)

    count = asyncio.get_event_loop().run_until_complete(_count())
    assert count == 2


@pytest.mark.integration
def test_escalate_cascade_delete_with_session(
    kb_client: httpx.Client, db: asyncpg.Connection
) -> None:
    """Hard-delete session → escalations CASCADE удалены."""
    import asyncio

    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    token = r1.headers["X-Chat-Session-Token"]
    kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/escalate",
        headers={"X-Chat-Session-Token": token},
    )

    async def _hard_delete_and_check() -> int:
        await db.execute("DELETE FROM chat_sessions WHERE id = $1", session_id)
        result = await db.fetchval(
            "SELECT count(*) FROM chat_escalations WHERE session_id = $1",
            session_id,
        )
        return int(result)

    count = asyncio.get_event_loop().run_until_complete(_hard_delete_and_check())
    assert count == 0


@pytest.mark.integration
def test_escalate_without_token_returns_404(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    """Owner mask: escalate без X-Chat-Session-Token → 404."""
    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)

    r2 = kb_client.post(f"/api/v1/chat/sessions/{session_id}/escalate")
    assert r2.status_code == 404


@pytest.mark.integration
def test_escalate_to_nonexistent_session_returns_404(
    kb_client: httpx.Client,
) -> None:
    r = kb_client.post(
        f"/api/v1/chat/sessions/{uuid4()}/escalate",
        headers={"X-Chat-Session-Token": str(uuid4())},
    )
    assert r.status_code == 404
