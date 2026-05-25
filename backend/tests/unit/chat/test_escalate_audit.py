"""E4.x #104: verify chat escalate writes audit_log row."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit.repository import AuditRepository, get_audit_repository
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
def audit_mock() -> Iterator[AsyncMock]:
    record = AsyncMock()
    fake = MagicMock(spec=AuditRepository)
    fake.record = record
    app.dependency_overrides[get_audit_repository] = lambda: fake
    yield record
    app.dependency_overrides.pop(get_audit_repository, None)


@pytest.fixture
def override_repo() -> Iterator[AsyncMock]:
    create = AsyncMock(return_value=None)
    repo = ChatRepository.__new__(ChatRepository)
    repo.create_escalation = create  # type: ignore[method-assign]
    # ADR-0026 Slice 2.
    repo.create_escalation_atomic = create  # type: ignore[method-assign]
    app.dependency_overrides[get_chat_repository] = lambda: repo

    # Session mock с поддержкой commit/refresh для atomic flow.
    from src.api.db import get_session

    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    async def _session_factory() -> Any:
        yield session

    app.dependency_overrides[get_session] = _session_factory
    yield create
    app.dependency_overrides.pop(get_chat_repository, None)
    app.dependency_overrides.pop(get_session, None)


def test_escalate_auth_writes_audit_with_jwt_sub(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_mock: AsyncMock,
    override_repo: AsyncMock,
) -> None:
    session = _make_session()
    esc = _make_escalation(session.id, priority="high")
    override_repo.return_value = esc

    actor_uuid = str(uuid4())
    token = make_jwt(roles=["tenant"], sub=actor_uuid)
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        json={"priority": "high"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["actor_sub"] == actor_uuid
    assert kwargs["action"] == "chat.escalated"
    assert kwargs["resource_type"] == "chat_session"
    assert kwargs["resource_id"] == str(session.id)
    assert kwargs["metadata"]["ticket_id"] == str(esc.id)
    assert kwargs["metadata"]["priority"] == "high"


def test_escalate_anon_writes_audit_with_anon_prefix(
    client: TestClient,
    audit_mock: AsyncMock,
    override_repo: AsyncMock,
) -> None:
    """Anon-flow: actor_sub = 'anon:<token-prefix>', не утечка ПДн."""
    session = _make_session()
    override_repo.return_value = _make_escalation(session.id)

    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        headers={"X-Chat-Session-Token": str(session.session_token)},
    )
    assert resp.status_code == 201
    audit_mock.assert_awaited_once()
    actor = audit_mock.call_args.kwargs["actor_sub"]
    assert actor.startswith("anon:")
    # Only 8-char prefix exposed.
    assert len(actor) == len("anon:") + 8


def test_escalate_404_does_not_write_audit(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_mock: AsyncMock,
    override_repo: AsyncMock,
) -> None:
    override_repo.return_value = None
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/escalate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    audit_mock.assert_not_awaited()


def test_escalate_does_not_leak_reason_in_audit(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_mock: AsyncMock,
    override_repo: AsyncMock,
) -> None:
    """ФЗ-152: reason (user-supplied free text) НЕ в audit metadata."""
    session = _make_session()
    override_repo.return_value = _make_escalation(session.id)

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        json={
            "reason": "Содержит ПДн: телефон +7-916-123-45-67",
            "priority": "high",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    audit_mock.assert_awaited_once()
    metadata = audit_mock.call_args.kwargs["metadata"]
    assert "reason" not in metadata
    assert "+7-916" not in str(metadata)
