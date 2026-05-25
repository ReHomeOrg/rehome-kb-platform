"""ADR-0026 Slice 3 atomic transaction guarantees для POST /collaborators.

Slice 3 invariant: webhook dispatch (`_dispatch_lifecycle_event`) теперь
ДО `session.commit()`. При OUTBOX_DRAINER_ENABLED=True outbox row пишется
в session-scope ДО commit'а — атомарно с collaborator + audit. При
failure (audit / dispatch) commit НЕ вызывается → rollback на session
close → ничего не persistится.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.collaborators.models import Collaborator
from src.api.collaborators.repository import (
    CollaboratorRepository,
    get_collaborator_repository,
)
from src.api.db import get_session
from src.api.main import app
from src.api.webhooks.dispatcher import (
    WebhookEventDispatcher,
    get_webhook_event_dispatcher,
)


def _payload() -> dict[str, Any]:
    return {"name": "ООО Атом", "type": "cleaning", "service_area": "Москва"}


def _passthrough_repo() -> CollaboratorRepository:
    async def _create(c: Collaborator) -> Collaborator:
        c.id = c.id or uuid4()
        c.created_at = c.created_at or datetime(2026, 5, 22, tzinfo=UTC)
        c.updated_at = c.updated_at or datetime(2026, 5, 22, tzinfo=UTC)
        c.audit_log = c.audit_log if c.audit_log is not None else []
        c.portal_access_level = c.portal_access_level or "NONE"
        c.portal_access_history = c.portal_access_history or []
        c.onboarding_source = c.onboarding_source or "staff_invite"
        return c

    repo = CollaboratorRepository.__new__(CollaboratorRepository)
    repo.create = AsyncMock(side_effect=_create)  # type: ignore[method-assign]
    return repo


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
def dispatcher_mock() -> Iterator[AsyncMock]:
    dispatch = AsyncMock(return_value=1)
    fake = MagicMock(spec=WebhookEventDispatcher)
    fake.dispatch = dispatch
    app.dependency_overrides[get_webhook_event_dispatcher] = lambda: fake
    yield dispatch
    app.dependency_overrides.pop(get_webhook_event_dispatcher, None)


@pytest.fixture
def repo_mock() -> Iterator[CollaboratorRepository]:
    repo = _passthrough_repo()
    app.dependency_overrides[get_collaborator_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_collaborator_repository, None)


def test_collab_create_calls_session_commit_once(
    client: TestClient,
    make_jwt: Callable[..., str],
    session_mock: MagicMock,
    dispatcher_mock: AsyncMock,
    repo_mock: CollaboratorRepository,
) -> None:
    """ADR-0026 Slice 3: collaborator + audit + dispatch atomic — единственный
    session.commit() в конце handler'а."""
    token = make_jwt(roles=["staff_admin"], sub="admin-1")
    resp = client.post(
        "/api/v1/collaborators",
        json=_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    session_mock.commit.assert_awaited_once()
    # Dispatch вызвана ДО commit'а (invariant Slice 3).
    dispatcher_mock.assert_awaited_once()


def test_collab_create_audit_failure_no_commit(
    client: TestClient,
    make_jwt: Callable[..., str],
    session_mock: MagicMock,
    dispatcher_mock: AsyncMock,
    repo_mock: CollaboratorRepository,
) -> None:
    """audit.record raises → handler propagates → commit НЕ вызван →
    collaborator row rollback'ится при session close."""
    fail_repo = MagicMock(spec=AuditRepository)
    fail_repo.record = AsyncMock(side_effect=RuntimeError("audit DB down"))
    app.dependency_overrides[get_audit_repository] = lambda: fail_repo
    try:
        token = make_jwt(roles=["staff_admin"], sub="admin-1")
        with pytest.raises(RuntimeError, match="audit DB down"):
            client.post(
                "/api/v1/collaborators",
                json=_payload(),
                headers={"Authorization": f"Bearer {token}"},
            )
        session_mock.commit.assert_not_awaited()
        # Dispatch не должен был случиться (audit ДО dispatch).
        dispatcher_mock.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_audit_repository, None)


def test_collab_create_dispatch_failure_no_commit(
    client: TestClient,
    make_jwt: Callable[..., str],
    session_mock: MagicMock,
    dispatcher_mock: AsyncMock,
    repo_mock: CollaboratorRepository,
) -> None:
    """dispatcher.dispatch raises → handler propagates → commit НЕ вызван →
    audit row тоже rollback'ится (atomic guarantee)."""
    dispatcher_mock.side_effect = RuntimeError("outbox enqueue failed")
    token = make_jwt(roles=["staff_admin"], sub="admin-1")
    with pytest.raises(RuntimeError, match="outbox enqueue failed"):
        client.post(
            "/api/v1/collaborators",
            json=_payload(),
            headers={"Authorization": f"Bearer {token}"},
        )
    session_mock.commit.assert_not_awaited()
