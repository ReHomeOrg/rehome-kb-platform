"""ADR-0026 Slice 2 atomic transaction guarantees для POST
/chat/sessions/{id}/escalate.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.chat.models import ChatEscalation, ChatSession
from src.api.chat.repository import ChatRepository, get_chat_repository
from src.api.db import get_session
from src.api.main import app


def _make_session_obj() -> ChatSession:
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


def _make_escalation(session_id: Any, priority: str = "normal") -> ChatEscalation:
    e = ChatEscalation()
    e.id = uuid4()
    e.session_id = session_id
    e.requested_by_user_id = uuid4()
    e.reason = None
    e.priority = priority
    e.status = "pending"
    e.requested_at = datetime.now(UTC)
    return e


@pytest.fixture
def session_mock() -> Iterator[MagicMock]:
    sess = MagicMock()
    sess.commit = AsyncMock()
    sess.rollback = AsyncMock()
    sess.refresh = AsyncMock()
    sess.add = MagicMock()
    sess.flush = AsyncMock()

    async def _factory() -> Any:
        yield sess

    app.dependency_overrides[get_session] = _factory
    yield sess
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def chat_repo_mock() -> Iterator[AsyncMock]:
    create_mock = AsyncMock()
    repo = ChatRepository.__new__(ChatRepository)
    repo.create_escalation = create_mock  # type: ignore[method-assign]
    repo.create_escalation_atomic = create_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_chat_repository] = lambda: repo
    yield create_mock
    app.dependency_overrides.pop(get_chat_repository, None)


def test_escalate_calls_session_commit_once(
    client: TestClient,
    session_mock: MagicMock,
    chat_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """ADR-0026 Slice 2: handler делает session.commit ровно один раз —
    atomic escalation + audit + (outbox если enabled)."""
    sess = _make_session_obj()
    esc = _make_escalation(sess.id)
    chat_repo_mock.return_value = esc

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{sess.id}/escalate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    session_mock.commit.assert_awaited_once()
    session_mock.refresh.assert_awaited_once_with(esc)


def test_escalate_404_no_commit(
    client: TestClient,
    session_mock: MagicMock,
    chat_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """`create_escalation_atomic` returns None → 404 → session.commit НЕ
    вызывается."""
    chat_repo_mock.return_value = None
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/escalate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    session_mock.commit.assert_not_awaited()


def test_escalate_audit_failure_no_commit(
    client: TestClient,
    session_mock: MagicMock,
    chat_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """audit_repo.record raises → handler propagates → session.commit НЕ
    вызывается → escalation rollback'ится при session close."""
    from src.api.audit.repository import AuditRepository, get_audit_repository

    sess = _make_session_obj()
    esc = _make_escalation(sess.id)
    chat_repo_mock.return_value = esc

    fail_repo = MagicMock(spec=AuditRepository)
    fail_repo.record = AsyncMock(side_effect=RuntimeError("audit DB down"))
    app.dependency_overrides[get_audit_repository] = lambda: fail_repo
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        with pytest.raises(RuntimeError, match="audit DB down"):
            client.post(
                f"/api/v1/chat/sessions/{sess.id}/escalate",
                headers={"Authorization": f"Bearer {token}"},
            )
        # CRITICAL invariant: session.commit НЕ вызвался.
        session_mock.commit.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_audit_repository, None)
