"""Unit tests для chat Prometheus metrics (#179, #181)."""

from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.chat.llm import LLMResponse, get_llm_provider
from src.api.chat.llm.base import LLMProvider
from src.api.chat.metrics import MESSAGE_DURATION_SECONDS, SESSIONS_CREATED_TOTAL
from src.api.chat.models import ChatMessage, ChatSession
from src.api.chat.repository import ChatRepository, get_chat_repository
from src.api.main import app


class _StreamLLM(LLMProvider):
    """Minimal LLMProvider yielding pre-scripted chunks."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    async def complete(
        self,
        messages: list[Any],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        text = "".join(self._chunks)
        return LLMResponse(content=text, token_count=len(text) // 4, duration_ms=10)

    async def stream(
        self,
        messages: list[Any],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        for chunk in self._chunks:
            yield chunk


def _make_session(user_id: object = None) -> ChatSession:
    s = ChatSession()
    s.id = uuid4()
    s.user_id = user_id  # type: ignore[assignment]
    s.session_token = uuid4()
    s.scope = "tenant" if user_id is not None else "guest"
    s.context = {}
    s.created_at = datetime.now(UTC)
    s.expires_at = datetime.now(UTC) + timedelta(days=1)
    s.deleted_at = None
    return s


def _counter_value(counter: Any, **labels: str) -> float:
    return float(counter.labels(**labels)._value.get())


@pytest.fixture
def override_create(monkeypatch: pytest.MonkeyPatch) -> Iterator[AsyncMock]:
    create_mock = AsyncMock()
    repo = ChatRepository.__new__(ChatRepository)
    repo.create_session = create_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_chat_repository] = lambda: repo
    yield create_mock
    app.dependency_overrides.pop(get_chat_repository, None)


def test_create_session_increments_sessions_counter_guest_scope(
    client: TestClient,
    override_create: AsyncMock,
) -> None:
    """Anon → SESSIONS_CREATED_TOTAL{scope=guest} +1."""
    override_create.return_value = _make_session(user_id=None)

    before = _counter_value(SESSIONS_CREATED_TOTAL, scope="guest")
    resp = client.post("/api/v1/chat/sessions")
    assert resp.status_code == 201
    after = _counter_value(SESSIONS_CREATED_TOTAL, scope="guest")
    assert after - before == 1.0


def _make_assistant_msg(session_id: object) -> ChatMessage:
    m = ChatMessage()
    m.id = uuid4()
    m.session_id = session_id  # type: ignore[assignment]
    m.role = "assistant"
    m.content = "hi"
    m.citations = []
    m.feedback = None
    m.token_count = None
    m.duration_ms = None
    m.created_at = datetime.now(UTC)
    return m


@pytest.fixture
def override_send(monkeypatch: pytest.MonkeyPatch) -> Iterator[ChatSession]:
    """Mock chat repo + LLM provider для send-message handler."""
    session = ChatSession()
    session.id = uuid4()
    session.user_id = uuid4()
    session.session_token = uuid4()
    session.scope = "tenant"
    session.context = {}
    session.created_at = datetime.now(UTC)
    session.expires_at = datetime.now(UTC) + timedelta(days=1)
    session.deleted_at = None

    repo = ChatRepository.__new__(ChatRepository)
    repo.get_session_by_owner = AsyncMock(return_value=session)  # type: ignore[method-assign]
    repo.list_messages = AsyncMock(return_value=[])  # type: ignore[method-assign]
    repo.record_chat_turn = AsyncMock(return_value=_make_assistant_msg(session.id))  # type: ignore[method-assign]
    app.dependency_overrides[get_chat_repository] = lambda: repo
    app.dependency_overrides[get_llm_provider] = lambda: _StreamLLM(["hi"])
    yield session
    app.dependency_overrides.pop(get_chat_repository, None)
    app.dependency_overrides.pop(get_llm_provider, None)


def _histogram_sum(histogram: Any) -> float:
    return float(histogram._sum.get())


def test_sse_message_observes_duration_histogram(
    client: TestClient,
    override_send: ChatSession,
    make_jwt: Callable[..., str],
) -> None:
    """SSE-режим теперь observes MESSAGE_DURATION_SECONDS (Cube DD)."""
    session = override_send
    token = make_jwt(roles=["tenant"], sub=str(session.user_id))

    before = _histogram_sum(MESSAGE_DURATION_SECONDS)
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "ping"},
        headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
    )
    # Consume full stream — generator's finally runs только когда iterator
    # exhausted.
    resp.read()
    assert resp.status_code == 200
    after = _histogram_sum(MESSAGE_DURATION_SECONDS)
    # Sum растёт на положительную duration; не assert'им точно.
    assert after > before
