"""Unit-тесты SSE-режима POST /chat/sessions/{id}/messages (E3.4 #67).

Покрывает:
- Accept: text/event-stream → 200 text/event-stream content-type.
- Stream events: message-start → chunks → message-end → done.
- LLM exception → event: error, no DB write.
- Empty stream (no chunks) → message-end + done с empty content.
- Owner-gate 404 mask.
- Body validation 422.
- Chunk granularity invariant: concat = full response.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.chat.llm import LLMResponse, MockProvider, get_llm_provider
from src.api.chat.llm.base import LLMProvider
from src.api.chat.models import ChatMessage, ChatSession
from src.api.chat.repository import ChatRepository, get_chat_repository
from src.api.main import app


def _make_session() -> ChatSession:
    s = ChatSession()
    s.id = uuid4()
    s.user_id = uuid4()
    s.session_token = uuid4()
    s.scope = "tenant"
    s.context = {}
    s.created_at = datetime.now(UTC)
    s.expires_at = datetime.now(UTC) + timedelta(days=1)
    s.deleted_at = None
    return s


def _make_message(session_id: object, role: str, content: str) -> ChatMessage:
    m = ChatMessage()
    m.id = uuid4()
    m.session_id = session_id  # type: ignore[assignment]
    m.role = role
    m.content = content
    m.citations = []
    m.feedback = None
    m.token_count = None
    m.duration_ms = None
    m.created_at = datetime.now(UTC)
    return m


class _ScriptedStreamProvider(LLMProvider):
    """LLMProvider, чьи stream/complete заданы скриптом."""

    def __init__(
        self,
        chunks: list[str] | None = None,
        raise_at: int | None = None,
    ) -> None:
        self._chunks = chunks or []
        self._raise_at = raise_at  # index, на котором поднять exception

    async def complete(
        self,
        messages: list,  # type: ignore[type-arg] # noqa: ARG002
        system_prompt: str,  # noqa: ARG002
        max_tokens: int = 1024,  # noqa: ARG002
    ) -> LLMResponse:
        text = "".join(self._chunks)
        return LLMResponse(content=text, token_count=len(text) // 4, duration_ms=42)

    async def stream(
        self,
        messages: list,  # type: ignore[type-arg] # noqa: ARG002
        system_prompt: str,  # noqa: ARG002
        max_tokens: int = 1024,  # noqa: ARG002
    ) -> AsyncIterator[str]:
        for i, chunk in enumerate(self._chunks):
            if self._raise_at == i:
                raise RuntimeError("scripted LLM failure")
            yield chunk


@pytest.fixture
def get_session_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def list_msgs_mock() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture
def record_turn_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def override_repo(
    get_session_mock: AsyncMock,
    list_msgs_mock: AsyncMock,
    record_turn_mock: AsyncMock,
) -> Iterator[tuple[AsyncMock, AsyncMock, AsyncMock]]:
    repo = ChatRepository.__new__(ChatRepository)
    repo.get_session_by_owner = get_session_mock  # type: ignore[method-assign]
    repo.list_messages = list_msgs_mock  # type: ignore[method-assign]
    repo.record_chat_turn = record_turn_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_chat_repository] = lambda: repo
    yield get_session_mock, list_msgs_mock, record_turn_mock
    app.dependency_overrides.pop(get_chat_repository, None)


def _override_llm(provider: LLMProvider) -> None:
    app.dependency_overrides[get_llm_provider] = lambda: provider


def _restore_llm() -> None:
    app.dependency_overrides.pop(get_llm_provider, None)


def _parse_sse_events(body: str) -> list[tuple[str, str]]:
    """Parse SSE stream → [(event_name, data_payload), ...]."""
    events = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = ""
        data = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        events.append((event_name, data))
    return events


# ---------------------------------------------------------------------------
# Happy path


def test_sse_returns_200_with_event_stream_content_type(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Accept: text/event-stream → 200, content-type text/event-stream."""
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="r")
    _override_llm(_ScriptedStreamProvider(chunks=["hello"]))
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        resp = client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
    finally:
        _restore_llm()


def test_sse_emits_message_start_chunks_message_end_done_in_order(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    assistant_msg = _make_message(session.id, role="assistant", content="ab")
    get_session_mock.return_value = session
    record_turn_mock.return_value = assistant_msg
    _override_llm(_ScriptedStreamProvider(chunks=["a", "b"]))
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        resp = client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        events = _parse_sse_events(resp.text)
        names = [name for name, _ in events]
        assert names == ["message-start", "chunk", "chunk", "message-end", "done"]
    finally:
        _restore_llm()


def test_sse_chunk_text_concat_equals_full_response(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Чанк-инвариант: concat всех chunk events == полный assistant content."""
    import json as _json

    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(
        session.id, role="assistant", content="hello world"
    )
    _override_llm(_ScriptedStreamProvider(chunks=["hello ", "world"]))
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        resp = client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        events = _parse_sse_events(resp.text)
        chunks = [_json.loads(data)["text"] for name, data in events if name == "chunk"]
        assert "".join(chunks) == "hello world"
    finally:
        _restore_llm()


def test_sse_message_end_contains_message_id_and_token_count(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    import json as _json

    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    assistant_msg = _make_message(session.id, role="assistant", content="xx")
    get_session_mock.return_value = session
    record_turn_mock.return_value = assistant_msg
    _override_llm(_ScriptedStreamProvider(chunks=["xx"]))
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        resp = client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        events = _parse_sse_events(resp.text)
        end_event = next(e for n, e in events if n == "message-end")
        data = _json.loads(end_event)
        assert data["message_id"] == str(assistant_msg.id)
        assert "total_tokens" in data
    finally:
        _restore_llm()


def test_sse_record_chat_turn_called_after_successful_stream(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="ok")
    _override_llm(_ScriptedStreamProvider(chunks=["o", "k"]))
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        record_turn_mock.assert_called_once()
        assert record_turn_mock.call_args.kwargs["assistant_content"] == "ok"
    finally:
        _restore_llm()


# ---------------------------------------------------------------------------
# Error handling — retry safety


def test_sse_llm_exception_emits_error_event_no_persist(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """LLM exception mid-stream → event: error, record_chat_turn НЕ вызван."""
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    # 2 chunks; exception на 2-м
    _override_llm(_ScriptedStreamProvider(chunks=["first ", "second"], raise_at=1))
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        resp = client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        names = [name for name, _ in events]
        # Должны быть: message-start, chunk (первый), error. Нет message-end / done.
        assert names == ["message-start", "chunk", "error"]
        # DB не тронута
        record_turn_mock.assert_not_called()
    finally:
        _restore_llm()


def test_sse_immediate_llm_failure_no_chunks(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """LLM падает на самом первом chunk'е — ни одного chunk-event."""
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    _override_llm(_ScriptedStreamProvider(chunks=["x"], raise_at=0))
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        resp = client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        events = _parse_sse_events(resp.text)
        names = [name for name, _ in events]
        assert names == ["message-start", "error"]
        record_turn_mock.assert_not_called()
    finally:
        _restore_llm()


def test_sse_empty_stream_still_persists_empty_message(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """LLM возвращает 0 chunks — assistant_content='' персистится, message-end + done."""
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="")
    _override_llm(_ScriptedStreamProvider(chunks=[]))
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        resp = client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
        )
        events = _parse_sse_events(resp.text)
        names = [name for name, _ in events]
        assert names == ["message-start", "message-end", "done"]
        record_turn_mock.assert_called_once()
        assert record_turn_mock.call_args.kwargs["assistant_content"] == ""
    finally:
        _restore_llm()


# ---------------------------------------------------------------------------
# Owner-gate + validation


def test_sse_no_identifier_returns_404(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
) -> None:
    get_session_mock, *_ = override_repo
    get_session_mock.return_value = None
    _override_llm(_ScriptedStreamProvider(chunks=["x"]))
    try:
        resp = client.post(
            f"/api/v1/chat/sessions/{uuid4()}/messages",
            json={"content": "x"},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 404
    finally:
        _restore_llm()


def test_sse_empty_content_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
) -> None:
    _override_llm(_ScriptedStreamProvider(chunks=["x"]))
    try:
        resp = client.post(
            f"/api/v1/chat/sessions/{uuid4()}/messages",
            json={"content": ""},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 422
    finally:
        _restore_llm()


# ---------------------------------------------------------------------------
# JSON-mode regression


def test_json_mode_unaffected_by_sse_changes(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Accept: application/json — JSON-mode unchanged (E3.3 behavior)."""
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="ok")

    complete_mock = AsyncMock(
        return_value=LLMResponse(content="ok", token_count=2, duration_ms=10),
    )
    provider = MockProvider.__new__(MockProvider)
    provider.complete = complete_mock  # type: ignore[method-assign]
    _override_llm(provider)
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        resp = client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        assert body["role"] == "assistant"
    finally:
        _restore_llm()
