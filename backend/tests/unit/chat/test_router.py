"""Unit-тесты для `/api/v1/chat/sessions/*` router (E3.2 #63).

Покрывает:
- POST /chat/sessions: anon flow (X-Chat-Session-Token в header), JWT
  flow (header отсутствует), context propagation, m2m JWT → anon flow,
  invalid JWT → 401.
- GET /chat/sessions/{id}: 200 с messages, 404 mask на cross-auth/no-id.
- DELETE /chat/sessions/{id}: 204, идемпотентность (повторный → 404),
  invalid UUID → 422.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.chat.models import ChatMessage, ChatSession
from src.api.chat.repository import ChatRepository, get_chat_repository
from src.api.main import app


def _make_session(user_id: object = None, session_token: object = None) -> ChatSession:
    s = ChatSession()
    s.id = uuid4()
    s.user_id = user_id  # type: ignore[assignment]
    s.session_token = session_token or uuid4()  # type: ignore[assignment]
    s.scope = "tenant" if user_id is not None else "guest"
    s.context = {}
    s.created_at = datetime.now(UTC)
    s.expires_at = datetime.now(UTC) + timedelta(days=1)
    s.deleted_at = None
    return s


def _make_message(session_id: object, role: str = "user", content: str = "hi") -> ChatMessage:
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
def create_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def get_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def list_msgs_mock() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture
def delete_mock() -> AsyncMock:
    return AsyncMock(return_value=False)


@pytest.fixture
def override_repo(
    create_mock: AsyncMock,
    get_mock: AsyncMock,
    list_msgs_mock: AsyncMock,
    delete_mock: AsyncMock,
) -> Iterator[tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]]:
    repo = ChatRepository.__new__(ChatRepository)
    repo.create_session = create_mock  # type: ignore[method-assign]
    repo.get_session_by_owner = get_mock  # type: ignore[method-assign]
    repo.list_messages = list_msgs_mock  # type: ignore[method-assign]
    repo.soft_delete_session = delete_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_chat_repository] = lambda: repo
    yield create_mock, get_mock, list_msgs_mock, delete_mock
    app.dependency_overrides.pop(get_chat_repository, None)


# ---------------------------------------------------------------------------
# POST /chat/sessions


def test_post_anon_returns_201_with_session_token_header(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    """Anon flow: 201 + X-Chat-Session-Token в response header."""
    create_mock, *_ = override_repo
    session = _make_session(user_id=None)
    create_mock.return_value = session

    resp = client.post("/api/v1/chat/sessions")
    assert resp.status_code == 201
    assert "X-Chat-Session-Token" in resp.headers
    assert resp.headers["X-Chat-Session-Token"] == str(session.session_token)

    body = resp.json()
    assert body["user_id"] is None
    assert body["scope"] == "guest"
    # session_token НЕ в body (security)
    assert "session_token" not in body


def test_post_with_jwt_returns_201_without_session_token_header(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Authorized flow: header X-Chat-Session-Token ОТСУТСТВУЕТ."""
    create_mock, *_ = override_repo
    user_id = uuid4()
    session = _make_session(user_id=user_id)
    create_mock.return_value = session

    token = make_jwt(roles=["tenant"], sub=str(user_id))
    resp = client.post(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert "X-Chat-Session-Token" not in resp.headers

    body = resp.json()
    assert body["user_id"] == str(user_id)
    assert body["scope"] == "tenant"


def test_post_with_context_propagates_to_repo(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    create_mock, *_ = override_repo
    create_mock.return_value = _make_session()

    premises_id = uuid4()
    resp = client.post(
        "/api/v1/chat/sessions",
        json={
            "context": {
                "page_url": "https://rehome.one/help",
                "premises_id": str(premises_id),
            }
        },
    )
    assert resp.status_code == 201
    ctx = create_mock.call_args.kwargs["context"]
    assert ctx["page_url"] == "https://rehome.one/help"
    assert ctx["premises_id"] == str(premises_id)


def test_post_invalid_jwt_returns_401(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    resp = client.post(
        "/api/v1/chat/sessions",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401


def test_post_m2m_jwt_non_uuid_sub_falls_back_to_anon_flow(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """m2m client_id обычно не UUID — graceful degradation в anon."""
    create_mock, *_ = override_repo
    create_mock.return_value = _make_session(user_id=None)

    token = make_jwt(roles=["staff_admin"], sub="service-account-rehome-platform-m2m")
    resp = client.post(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    # user_id=None в repo call
    assert create_mock.call_args.kwargs["user_id"] is None
    # X-Chat-Session-Token в headers (anon)
    assert "X-Chat-Session-Token" in resp.headers


def test_post_empty_body_works(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    """Полностью пустой body (без Content-Type/JSON) → 201, context={}."""
    create_mock, *_ = override_repo
    create_mock.return_value = _make_session(user_id=None)

    resp = client.post("/api/v1/chat/sessions")
    assert resp.status_code == 201
    assert create_mock.call_args.kwargs["context"] == {}


def test_post_empty_json_object_works(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    """JSON `{}` → 201, context={}."""
    create_mock, *_ = override_repo
    create_mock.return_value = _make_session(user_id=None)

    resp = client.post("/api/v1/chat/sessions", json={})
    assert resp.status_code == 201
    assert create_mock.call_args.kwargs["context"] == {}


def test_post_context_with_unknown_field_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    """ChatContext extra='forbid' — unknown field → 422."""
    resp = client.post(
        "/api/v1/chat/sessions",
        json={"context": {"unknown_field": "x"}},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /chat/sessions/{id}


def test_get_session_existing_returns_200_with_messages(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    _, get_mock, list_msgs_mock, _ = override_repo
    user_id = uuid4()
    session = _make_session(user_id=user_id)
    msg = _make_message(session.id, role="user", content="hello")
    get_mock.return_value = session
    list_msgs_mock.return_value = [msg]

    resp = client.get(f"/api/v1/chat/sessions/{session.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(session.id)
    assert len(body["messages"]) == 1
    assert body["messages"][0]["content"] == "hello"


def test_get_session_nonexistent_returns_404(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    _, get_mock, _, _ = override_repo
    get_mock.return_value = None

    resp = client.get(f"/api/v1/chat/sessions/{uuid4()}")
    assert resp.status_code == 404


def test_get_session_no_identifier_returns_404_mask(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    """Без JWT и без X-Chat-Session-Token → repo вернёт None → 404."""
    _, get_mock, _, _ = override_repo
    get_mock.return_value = None

    resp = client.get(f"/api/v1/chat/sessions/{uuid4()}")
    assert resp.status_code == 404


def test_get_session_with_session_token_header(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    """Anon GET с X-Chat-Session-Token — token парсится и передаётся в repo."""
    _, get_mock, list_msgs_mock, _ = override_repo
    token = uuid4()
    session = _make_session(session_token=token)
    get_mock.return_value = session
    list_msgs_mock.return_value = []

    resp = client.get(
        f"/api/v1/chat/sessions/{session.id}",
        headers={"X-Chat-Session-Token": str(token)},
    )
    assert resp.status_code == 200
    # Repo вызвался с session_token=token
    assert get_mock.call_args.kwargs["session_token"] == token


def test_get_session_invalid_session_token_header_returns_404(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    """Битый header → token=None → repo вернёт None → 404."""
    _, get_mock, _, _ = override_repo
    get_mock.return_value = None

    resp = client.get(
        f"/api/v1/chat/sessions/{uuid4()}",
        headers={"X-Chat-Session-Token": "not-a-uuid"},
    )
    assert resp.status_code == 404


def test_get_session_invalid_uuid_path_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/chat/sessions/not-a-uuid")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /chat/sessions/{id}


def test_delete_existing_returns_204(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    _, _, _, delete_mock = override_repo
    delete_mock.return_value = True

    user_id = uuid4()
    token = make_jwt(roles=["tenant"], sub=str(user_id))
    resp = client.delete(
        f"/api/v1/chat/sessions/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204


def test_delete_nonexistent_returns_404(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    _, _, _, delete_mock = override_repo
    delete_mock.return_value = False

    resp = client.delete(f"/api/v1/chat/sessions/{uuid4()}")
    assert resp.status_code == 404


def test_delete_idempotent_second_call_returns_404(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    """Первый DELETE возвращает True (204), второй — False (404)."""
    _, _, _, delete_mock = override_repo
    delete_mock.side_effect = [True, False]

    sid = uuid4()
    token_header = {"X-Chat-Session-Token": str(uuid4())}
    r1 = client.delete(f"/api/v1/chat/sessions/{sid}", headers=token_header)
    r2 = client.delete(f"/api/v1/chat/sessions/{sid}", headers=token_header)
    assert r1.status_code == 204
    assert r2.status_code == 404


def test_delete_invalid_uuid_path_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock],
) -> None:
    resp = client.delete("/api/v1/chat/sessions/not-a-uuid")
    assert resp.status_code == 422
