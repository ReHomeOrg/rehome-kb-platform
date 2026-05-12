"""Integration: end-to-end SSE streaming через httpx (E3.4 #67).

Покрывает:
- POST с Accept: text/event-stream → consume stream → 5 events
  (message-start, chunk(s), message-end, done).
- После consume — assistant message в БД.
- JSON-mode regression: Accept: application/json всё ещё работает.

NB: backend MUST run с LLM_PROVIDER=mock (default).
"""

import json
import os
from collections.abc import AsyncIterator

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


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = ""
        data: dict[str, object] = {}
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                parsed = json.loads(line[len("data: ") :])
                assert isinstance(parsed, dict)
                data = parsed
        events.append((event_name, data))
    return events


@pytest.mark.integration
def test_sse_e2e_consumes_full_stream(kb_client: httpx.Client, cleanup_sessions: list[str]) -> None:
    """POST → Accept SSE → events последовательны и polno-formed."""
    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)
    token = r1.headers["X-Chat-Session-Token"]

    with kb_client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Привет"},
        headers={
            "X-Chat-Session-Token": token,
            "Accept": "text/event-stream",
        },
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.read().decode("utf-8")

    events = _parse_sse(body)
    names = [n for n, _ in events]
    assert names[0] == "message-start"
    assert names[-1] == "done"
    assert names[-2] == "message-end"
    # Должен быть хотя бы один chunk
    assert any(n == "chunk" for n in names)

    # message-end содержит message_id + total_tokens
    end_data = next(d for n, d in events if n == "message-end")
    assert "message_id" in end_data
    assert "total_tokens" in end_data


@pytest.mark.integration
def test_sse_e2e_persists_assistant_message(
    kb_client: httpx.Client, cleanup_sessions: list[str], db: asyncpg.Connection
) -> None:
    """После consume SSE stream'а — assistant message в DB."""
    import asyncio

    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)
    token = r1.headers["X-Chat-Session-Token"]

    with kb_client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Сколько стоит сервисный платёж?"},
        headers={
            "X-Chat-Session-Token": token,
            "Accept": "text/event-stream",
        },
    ) as resp:
        resp.read()  # consume

    async def _count() -> int:
        result = await db.fetchval(
            "SELECT count(*) FROM chat_messages WHERE session_id = $1",
            session_id,
        )
        return int(result)

    count = asyncio.get_event_loop().run_until_complete(_count())
    assert count == 2  # user + assistant


@pytest.mark.integration
def test_json_mode_still_works_after_sse_landing(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    """Regression: Accept: application/json → JSON-mode без regression."""
    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)
    token = r1.headers["X-Chat-Session-Token"]

    r2 = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Привет"},
        headers={
            "X-Chat-Session-Token": token,
            "Accept": "application/json",
        },
    )
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("application/json")
    assert r2.json()["role"] == "assistant"
