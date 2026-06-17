"""Integration: end-to-end POST /api/v1/chat/sessions/{id}/messages (E3.3 #65).

Покрывает:
- POST → 200, assistant ответ записан в БД.
- Conversation continuity: оба хода сохранены (history передаётся в LLM
  call; mock-провайдер в RAG-режиме больше не echo'ит last user —
  continuity проверяем по числу сообщений в сессии).
- POST без token → 404 mask.
- Accept: text/event-stream → 406.

NB: env LLM_PROVIDER должен быть 'mock' (default).
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
    ids: list[str] = []
    yield ids
    for sid in ids:
        await db.execute("DELETE FROM chat_sessions WHERE id = $1", sid)


@pytest.mark.integration
def test_post_message_e2e_creates_assistant_response(
    kb_client: httpx.Client, cleanup_sessions: list[str], db: asyncpg.Connection
) -> None:
    """End-to-end: create session → POST message → assistant ответ."""
    import asyncio

    r1 = kb_client.post("/api/v1/chat/sessions")
    assert r1.status_code == 201
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)
    token = r1.headers["X-Chat-Session-Token"]

    r2 = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Какой сервисный платёж?"},
        headers={"X-Chat-Session-Token": token},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["role"] == "assistant"
    # MockProvider в RAG-пайплайне отдаёт детерминированный ответ
    # AI-ассистента (echo-контракт снят при переходе на RAG; в CI БД пустая
    # → ветка «не нашлось статей»). Проверяем, что ассистент реально ответил.
    assert "AI-ассистент" in body["content"]
    assert body["token_count"] > 0
    assert body["duration_ms"] >= 0

    # Verify в БД 2 сообщения (user + assistant)
    async def _count() -> int:
        result = await db.fetchval(
            "SELECT count(*) FROM chat_messages WHERE session_id = $1",
            session_id,
        )
        return int(result)

    count = asyncio.get_event_loop().run_until_complete(_count())
    assert count == 2


@pytest.mark.integration
def test_post_message_continuity_includes_history(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    """2nd POST: оба хода сохраняются; continuity проверяем по числу
    сообщений в сессии (history передаётся в LLM call, но mock-провайдер
    в RAG-режиме больше не echo'ит — см. src/api/chat/llm/mock.py)."""
    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)
    token = r1.headers["X-Chat-Session-Token"]
    auth = {"X-Chat-Session-Token": token}

    kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "первый вопрос"},
        headers=auth,
    )
    r3 = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "второй вопрос"},
        headers=auth,
    )
    assert r3.status_code == 200
    assert "AI-ассистент" in r3.json()["content"]

    # Verify GET session detail возвращает 4 messages (2 user + 2 assistant)
    r4 = kb_client.get(
        f"/api/v1/chat/sessions/{session_id}",
        headers=auth,
    )
    assert len(r4.json()["messages"]) == 4


@pytest.mark.integration
def test_post_message_without_token_returns_404(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    """ADR-0003 mask: создали session → POST без token → 404."""
    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)

    r2 = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "x"},
    )
    assert r2.status_code == 404


# SSE Accept handling — раньше возвращал 406 (E3.3 placeholder).
# E3.4 (#67) реализовал реальный streaming; тесты для SSE — в
# tests/integration/test_chat_sse.py.


@pytest.mark.integration
def test_post_message_content_too_long_returns_422(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    cleanup_sessions.append(session_id)
    token = r1.headers["X-Chat-Session-Token"]

    r2 = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "x" * 2001},
        headers={"X-Chat-Session-Token": token},
    )
    assert r2.status_code == 422


@pytest.mark.integration
def test_post_message_to_nonexistent_session_returns_404(
    kb_client: httpx.Client,
) -> None:
    r2 = kb_client.post(
        f"/api/v1/chat/sessions/{uuid4()}/messages",
        json={"content": "x"},
        headers={"X-Chat-Session-Token": str(uuid4())},
    )
    assert r2.status_code == 404
