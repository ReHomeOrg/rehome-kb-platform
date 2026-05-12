"""Unit-тесты POST /api/v1/chat/sessions/{id}/messages (E3.3 #65).

Покрывает:
- 200 + assistant ChatMessageResponse.
- Body validation: content empty/missing/too long → 422.
- Owner-gate: no-id / wrong-token → 404.
- Authorized JWT / anon session_token / invalid JWT 401.
- LLM call: SYSTEM_PROMPT передан, history передана.
- LLM exception → 5xx, ничего не записано.
- Accept: text/event-stream → 406 (SSE deferred to E3.4).
- Accept: */* → 200 (browser default fallthrough).
- citations всегда [] в E3.3.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.chat.llm import LLMMessage, LLMResponse, MockProvider, get_llm_provider
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


@pytest.fixture
def override_llm() -> Iterator[AsyncMock]:
    """Override LLMProvider с настраиваемой mock-complete()."""
    complete_mock = AsyncMock(
        return_value=LLMResponse(content="reply", token_count=10, duration_ms=42),
    )
    provider = MockProvider.__new__(MockProvider)
    provider.complete = complete_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_llm_provider] = lambda: provider
    yield complete_mock
    app.dependency_overrides.pop(get_llm_provider, None)


# ---------------------------------------------------------------------------
# Happy path


def test_post_message_returns_200_with_assistant_response(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    get_session_mock, list_msgs_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    list_msgs_mock.return_value = []
    assistant_msg = _make_message(session.id, role="assistant", content="reply")
    record_turn_mock.return_value = assistant_msg

    user_id = uuid4()
    token = make_jwt(roles=["tenant"], sub=str(user_id))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "Привет"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "assistant"
    assert body["content"] == "reply"


def test_post_message_calls_llm_with_history_plus_new_user(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """history + new user content передаются в llm.complete."""
    get_session_mock, list_msgs_mock, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    list_msgs_mock.return_value = [
        _make_message(session.id, role="user", content="prev q"),
        _make_message(session.id, role="assistant", content="prev a"),
    ]
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="reply")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "new q"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # llm.complete получил [prev_q, prev_a, new_q]
    llm_messages = override_llm.call_args.args[0]
    assert len(llm_messages) == 3
    assert llm_messages[-1] == LLMMessage(role="user", content="new q")


def test_post_message_passes_system_prompt_to_llm(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """SYSTEM_PROMPT передаётся в llm.complete."""
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "q"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Second positional arg — system_prompt
    sys_prompt = override_llm.call_args.args[1]
    assert "reHome" in sys_prompt
    assert len(sys_prompt) > 100  # not empty


def test_post_message_citations_always_empty_in_e33(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """В E3.3 RAG нет — record_chat_turn получает citations=[]."""
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="x")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "q"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert record_turn_mock.call_args.kwargs["citations"] == []


# ---------------------------------------------------------------------------
# Body validation


def test_post_message_empty_content_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/messages",
        json={"content": ""},
    )
    assert resp.status_code == 422


def test_post_message_missing_content_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
) -> None:
    resp = client.post(f"/api/v1/chat/sessions/{uuid4()}/messages", json={})
    assert resp.status_code == 422


def test_post_message_too_long_content_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/messages",
        json={"content": "x" * 2001},
    )
    assert resp.status_code == 422


def test_post_message_invalid_uuid_path_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
) -> None:
    resp = client.post(
        "/api/v1/chat/sessions/not-a-uuid/messages",
        json={"content": "x"},
    )
    assert resp.status_code == 422


def test_post_message_extra_field_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
) -> None:
    """extra='forbid' на SendMessageInput."""
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/messages",
        json={"content": "x", "extra": "field"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Owner / auth


def test_post_message_no_identifier_returns_404(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
) -> None:
    """Без JWT и без X-Chat-Session-Token → repo.get_session_by_owner None → 404."""
    get_session_mock, *_ = override_repo
    get_session_mock.return_value = None

    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/messages",
        json={"content": "x"},
    )
    assert resp.status_code == 404


def test_post_message_wrong_session_token_returns_404(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
) -> None:
    get_session_mock, *_ = override_repo
    get_session_mock.return_value = None
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/messages",
        json={"content": "x"},
        headers={"X-Chat-Session-Token": str(uuid4())},
    )
    assert resp.status_code == 404


def test_post_message_invalid_jwt_returns_401(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/messages",
        json={"content": "x"},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401


def test_post_message_anon_with_session_token_works(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
) -> None:
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="ok")

    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "q"},
        headers={"X-Chat-Session-Token": str(session.session_token)},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# SSE Accept handling — E3.4 landed real streaming.
# Detailed SSE tests перенесены в test_messages_sse.py. Здесь оставляем
# только wildcard regression — гарантия что */* всё ещё JSON-mode.


def test_post_message_wildcard_accept_returns_json(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Accept: */* (browser default) → JSON 200, not 406."""
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    record_turn_mock.return_value = _make_message(session.id, role="assistant", content="ok")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"content": "q"},
        headers={"Authorization": f"Bearer {token}", "Accept": "*/*"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# LLM failure → no partial write


def test_post_message_llm_exception_does_not_write_db(
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    override_llm: AsyncMock,
    make_jwt: Callable[..., str],
    test_settings: object,
) -> None:
    """LLM raises → 5xx; record_chat_turn НЕ вызывался → DB не тронута.

    Retry-safety: клиент может повторить запрос без duplicate user message.

    NB: используем отдельный TestClient(raise_server_exceptions=False) —
    дефолтный fixture'овский поднимает exception через, нам нужен
    конверт в 500 response.
    """
    get_session_mock, _, record_turn_mock = override_repo
    session = _make_session()
    get_session_mock.return_value = session
    override_llm.side_effect = RuntimeError("LLM upstream down")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    with TestClient(app, raise_server_exceptions=False) as silent_client:
        resp = silent_client.post(
            f"/api/v1/chat/sessions/{session.id}/messages",
            json={"content": "q"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code >= 500
    # КРИТИЧНО: record_chat_turn НЕ был вызван — DB не тронута
    record_turn_mock.assert_not_called()
