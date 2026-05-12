"""Unit-тесты POST /api/v1/chat/sessions/{id}/escalate (E3.6 #71)."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.chat.models import ChatEscalation, ChatSession
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


def _make_escalation(session_id: object, priority: str = "normal") -> ChatEscalation:
    e = ChatEscalation()
    e.id = uuid4()
    e.session_id = session_id  # type: ignore[assignment]
    e.requested_by_user_id = uuid4()
    e.reason = None
    e.priority = priority
    e.status = "pending"
    e.requested_at = datetime.now(UTC)
    return e


@pytest.fixture
def create_escalation_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def override_repo(create_escalation_mock: AsyncMock) -> Iterator[AsyncMock]:
    repo = ChatRepository.__new__(ChatRepository)
    repo.create_escalation = create_escalation_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_chat_repository] = lambda: repo
    yield create_escalation_mock
    app.dependency_overrides.pop(get_chat_repository, None)


# ---------------------------------------------------------------------------
# Happy path


def test_escalate_with_jwt_returns_201_with_ticket_id(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    session = _make_session()
    esc = _make_escalation(session.id, priority="normal")
    override_repo.return_value = esc

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["ticket_id"] == str(esc.id)
    assert body["estimated_response_time_minutes"] == 30  # normal


def test_escalate_with_anon_session_token_returns_201(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    session = _make_session()
    esc = _make_escalation(session.id)
    override_repo.return_value = esc

    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        headers={"X-Chat-Session-Token": str(session.session_token)},
    )
    assert resp.status_code == 201


def test_escalate_empty_body_uses_default_priority_normal(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    session = _make_session()
    override_repo.return_value = _make_escalation(session.id, priority="normal")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        headers={"Authorization": f"Bearer {token}"},
    )
    # repo получил default priority='normal', reason=None
    kwargs = override_repo.call_args.kwargs
    assert kwargs["priority"] == "normal"
    assert kwargs["reason"] is None


def test_escalate_low_priority_returns_60_minutes(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    session = _make_session()
    override_repo.return_value = _make_escalation(session.id, priority="low")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        json={"priority": "low"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["estimated_response_time_minutes"] == 60


def test_escalate_high_priority_returns_10_minutes(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    session = _make_session()
    override_repo.return_value = _make_escalation(session.id, priority="high")

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        json={"priority": "high"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["estimated_response_time_minutes"] == 10


def test_escalate_passes_reason_to_repo(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    session = _make_session()
    override_repo.return_value = _make_escalation(session.id)

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        json={"reason": "Не отвечает по теме"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert override_repo.call_args.kwargs["reason"] == "Не отвечает по теме"


# ---------------------------------------------------------------------------
# Owner mask


def test_escalate_repo_returns_none_yields_404(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    override_repo.return_value = None
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/escalate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_escalate_no_identifier_returns_404(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    override_repo.return_value = None
    resp = client.post(f"/api/v1/chat/sessions/{uuid4()}/escalate")
    assert resp.status_code == 404


def test_escalate_invalid_jwt_returns_401(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/escalate",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Body validation


def test_escalate_invalid_priority_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/escalate",
        json={"priority": "urgent"},
    )
    assert resp.status_code == 422


def test_escalate_extra_field_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/escalate",
        json={"priority": "normal", "unknown": "x"},
    )
    assert resp.status_code == 422


def test_escalate_reason_too_long_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/escalate",
        json={"reason": "x" * 2001},
    )
    assert resp.status_code == 422


def test_escalate_invalid_uuid_path_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.post("/api/v1/chat/sessions/not-a-uuid/escalate")
    assert resp.status_code == 422
