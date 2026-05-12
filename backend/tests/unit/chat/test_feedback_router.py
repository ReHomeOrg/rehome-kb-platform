"""Unit-тесты POST /api/v1/chat/sessions/{id}/feedback (E3.5 #69).

Покрывает:
- 201 на success.
- Body validation: missing message_id, invalid rating, comment > 1000,
  extra field, invalid UUID path.
- Owner mask: repo.set_feedback returns None → 404.
- JWT/anon/invalid scenarios.
- repo получает правильный rating и comment.
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


def _make_message(session_id: object) -> ChatMessage:
    m = ChatMessage()
    m.id = uuid4()
    m.session_id = session_id  # type: ignore[assignment]
    m.role = "assistant"
    m.content = "x"
    m.citations = []
    m.feedback = None
    m.token_count = None
    m.duration_ms = None
    m.created_at = datetime.now(UTC)
    return m


@pytest.fixture
def set_feedback_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def override_repo(set_feedback_mock: AsyncMock) -> Iterator[AsyncMock]:
    repo = ChatRepository.__new__(ChatRepository)
    repo.set_feedback = set_feedback_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_chat_repository] = lambda: repo
    yield set_feedback_mock
    app.dependency_overrides.pop(get_chat_repository, None)


# ---------------------------------------------------------------------------
# Happy path


def test_post_feedback_with_jwt_returns_201(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    session = _make_session()
    msg = _make_message(session.id)
    msg.feedback = {"rating": "up", "comment": "good"}
    override_repo.return_value = msg

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/feedback",
        json={"message_id": str(msg.id), "rating": "up", "comment": "good"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201


def test_post_feedback_with_session_token_returns_201(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    session = _make_session()
    msg = _make_message(session.id)
    override_repo.return_value = msg

    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/feedback",
        json={"message_id": str(msg.id), "rating": "down"},
        headers={"X-Chat-Session-Token": str(session.session_token)},
    )
    assert resp.status_code == 201


def test_post_feedback_passes_payload_to_repo(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    session = _make_session()
    msg = _make_message(session.id)
    override_repo.return_value = msg

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    client.post(
        f"/api/v1/chat/sessions/{session.id}/feedback",
        json={"message_id": str(msg.id), "rating": "up", "comment": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = override_repo.call_args.kwargs
    assert kwargs["rating"] == "up"
    assert kwargs["comment"] == "hello"
    assert kwargs["session_id"] == session.id


def test_post_feedback_without_comment_passes_none(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    session = _make_session()
    msg = _make_message(session.id)
    override_repo.return_value = msg

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    client.post(
        f"/api/v1/chat/sessions/{session.id}/feedback",
        json={"message_id": str(msg.id), "rating": "down"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert override_repo.call_args.kwargs["comment"] is None


# ---------------------------------------------------------------------------
# Owner mask


def test_post_feedback_repo_returns_none_yields_404(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """ADR-0003 mask: repo None → 404 (session/message не видна)."""
    override_repo.return_value = None
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/feedback",
        json={"message_id": str(uuid4()), "rating": "up"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_post_feedback_no_identifier_returns_404(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    override_repo.return_value = None
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/feedback",
        json={"message_id": str(uuid4()), "rating": "up"},
    )
    assert resp.status_code == 404


def test_post_feedback_invalid_jwt_returns_401(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/feedback",
        json={"message_id": str(uuid4()), "rating": "up"},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Body validation


def test_post_feedback_missing_message_id_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/feedback",
        json={"rating": "up"},
    )
    assert resp.status_code == 422


def test_post_feedback_missing_rating_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/feedback",
        json={"message_id": str(uuid4())},
    )
    assert resp.status_code == 422


def test_post_feedback_invalid_rating_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/feedback",
        json={"message_id": str(uuid4()), "rating": "neutral"},
    )
    assert resp.status_code == 422


def test_post_feedback_comment_too_long_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/feedback",
        json={"message_id": str(uuid4()), "rating": "up", "comment": "x" * 1001},
    )
    assert resp.status_code == 422


def test_post_feedback_extra_field_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/feedback",
        json={
            "message_id": str(uuid4()),
            "rating": "up",
            "unknown": "field",
        },
    )
    assert resp.status_code == 422


def test_post_feedback_invalid_uuid_path_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        "/api/v1/chat/sessions/not-a-uuid/feedback",
        json={"message_id": str(uuid4()), "rating": "up"},
    )
    assert resp.status_code == 422


def test_post_feedback_invalid_message_id_uuid_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/feedback",
        json={"message_id": "not-a-uuid", "rating": "up"},
    )
    assert resp.status_code == 422
