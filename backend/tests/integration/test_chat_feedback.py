"""Integration: POST /api/v1/chat/sessions/{id}/feedback (E3.5 #69).

Покрывает:
- End-to-end: session → message → feedback → GET session содержит feedback в message.
- Cross-session защита: feedback на message из другой session → 404.
- Idempotent overwrite: 2 feedback'а на тот же message → последний.
"""

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


def _create_session_with_message(
    kb_client: httpx.Client,
) -> tuple[str, str, str]:
    """Helper: создаёт session + 1 сообщение, возвращает (session_id, token, msg_id)."""
    r1 = kb_client.post("/api/v1/chat/sessions")
    session_id = r1.json()["id"]
    token = r1.headers["X-Chat-Session-Token"]
    r2 = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "тестовый вопрос"},
        headers={"X-Chat-Session-Token": token},
    )
    assistant_id = r2.json()["id"]
    return session_id, token, assistant_id


@pytest.mark.integration
def test_e2e_post_feedback_then_visible_in_get_session(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    """POST feedback → 201; GET session возвращает message с feedback."""
    session_id, token, msg_id = _create_session_with_message(kb_client)
    cleanup_sessions.append(session_id)

    r3 = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/feedback",
        json={"message_id": msg_id, "rating": "up", "comment": "помогло"},
        headers={"X-Chat-Session-Token": token},
    )
    assert r3.status_code == 201, r3.text

    r4 = kb_client.get(
        f"/api/v1/chat/sessions/{session_id}",
        headers={"X-Chat-Session-Token": token},
    )
    messages = r4.json()["messages"]
    assistant_msg = next(m for m in messages if m["id"] == msg_id)
    assert assistant_msg["feedback"] == {"rating": "up", "comment": "помогло"}


@pytest.mark.integration
def test_cross_session_feedback_returns_404(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    """Feedback на message из ДРУГОЙ session → 404 (ADR-0003 mask)."""
    session_a, token_a, msg_a = _create_session_with_message(kb_client)
    session_b, token_b, _ = _create_session_with_message(kb_client)
    cleanup_sessions.extend([session_a, session_b])

    # Шлём feedback на msg_a, указав session_b в path
    r = kb_client.post(
        f"/api/v1/chat/sessions/{session_b}/feedback",
        json={"message_id": msg_a, "rating": "up"},
        headers={"X-Chat-Session-Token": token_b},
    )
    assert r.status_code == 404


@pytest.mark.integration
def test_feedback_idempotent_overwrite(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    """Повторный POST с другим rating перезаписывает feedback."""
    session_id, token, msg_id = _create_session_with_message(kb_client)
    cleanup_sessions.append(session_id)

    kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/feedback",
        json={"message_id": msg_id, "rating": "up", "comment": "first"},
        headers={"X-Chat-Session-Token": token},
    )
    kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/feedback",
        json={"message_id": msg_id, "rating": "down", "comment": "second"},
        headers={"X-Chat-Session-Token": token},
    )

    r = kb_client.get(
        f"/api/v1/chat/sessions/{session_id}",
        headers={"X-Chat-Session-Token": token},
    )
    messages = r.json()["messages"]
    msg = next(m for m in messages if m["id"] == msg_id)
    assert msg["feedback"] == {"rating": "down", "comment": "second"}


@pytest.mark.integration
def test_feedback_without_token_returns_404(
    kb_client: httpx.Client, cleanup_sessions: list[str]
) -> None:
    session_id, _token, msg_id = _create_session_with_message(kb_client)
    cleanup_sessions.append(session_id)

    r = kb_client.post(
        f"/api/v1/chat/sessions/{session_id}/feedback",
        json={"message_id": msg_id, "rating": "up"},
    )
    assert r.status_code == 404
