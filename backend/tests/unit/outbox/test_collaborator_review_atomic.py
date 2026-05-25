"""ADR-0026 Slice 2 atomic transaction guarantees для POST
/collaborators/{id}/reviews.

Тест pattern: session_mock + check что commit вызывается ровно один раз
(вместо двух раз как было до Slice 2 refactor'а: один для review.insert,
второй для audit/commit).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.collaborators.models import Collaborator, CollaboratorReview
from src.api.db import get_session
from src.api.main import app


def _make_collab(group: str = "D") -> Collaborator:
    c = Collaborator()
    c.id = uuid4()
    c.financial_group = group
    c.rating = Decimal("4.5")
    return c


@pytest.fixture
def session_mock() -> Iterator[MagicMock]:
    """Session с tracking commit calls. _check_collaborator_visible
    использует session.execute, поэтому stub'аем execute returning collab.
    """
    sess = MagicMock()
    sess.commit = AsyncMock()
    sess.rollback = AsyncMock()
    sess.refresh = AsyncMock()
    sess.add = MagicMock()
    sess.flush = AsyncMock()

    # _check_collaborator_visible → session.execute(SELECT collab WHERE...).
    # _recompute_rating → session.execute(SELECT AVG) + session.execute(UPDATE).
    collab = _make_collab("D")

    select_collab_result = MagicMock()
    select_collab_result.scalar_one_or_none = MagicMock(return_value=collab)
    avg_result = MagicMock()
    avg_result.scalar_one_or_none = MagicMock(return_value=Decimal("4.5"))
    update_result = MagicMock()

    # Order: SELECT collab visible → SELECT AVG (recompute) → UPDATE rating.
    sess.execute = AsyncMock(side_effect=[select_collab_result, avg_result, update_result])
    sess._test_collab = collab  # для test access

    async def _factory() -> Any:
        yield sess

    app.dependency_overrides[get_session] = _factory
    yield sess
    app.dependency_overrides.pop(get_session, None)


def _flush_with_defaults_factory(session_mock: MagicMock) -> AsyncMock:
    """Factory: imitates server-side id/created_at defaults через flush."""
    review_id = uuid4()

    async def _flush_with_defaults() -> None:
        for call in session_mock.add.call_args_list:
            obj = call.args[0]
            if isinstance(obj, CollaboratorReview):
                if obj.id is None:
                    obj.id = review_id
                if obj.created_at is None:
                    obj.created_at = datetime.now(UTC)

    return AsyncMock(side_effect=_flush_with_defaults)


def test_review_post_calls_session_commit_once(
    client: TestClient,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """ADR-0026 Slice 2: session.commit ровно один раз (раньше — два:
    commit() ВНУТРИ handler + потенциальный rollback). Webhook dispatch
    теперь ДО commit'а — atomic с review + audit + rating UPDATE."""
    session_mock.flush = _flush_with_defaults_factory(session_mock)
    collab = session_mock._test_collab

    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{collab.id}/reviews",
        headers={"Authorization": f"Bearer {token}"},
        json={"rating": 5, "comment": "ok"},
    )
    assert resp.status_code == 201, resp.text
    # Single commit — atomic transaction.
    session_mock.commit.assert_awaited_once()


def test_review_post_audit_failure_no_commit(
    client: TestClient,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """audit_repo.record raises → handler propagates → commit НЕ вызван."""
    from src.api.audit.repository import AuditRepository, get_audit_repository

    session_mock.flush = _flush_with_defaults_factory(session_mock)
    collab = session_mock._test_collab

    fail_repo = MagicMock(spec=AuditRepository)
    fail_repo.record = AsyncMock(side_effect=RuntimeError("audit DB down"))
    app.dependency_overrides[get_audit_repository] = lambda: fail_repo
    try:
        token = make_jwt(roles=["tenant"], sub=str(uuid4()))
        with pytest.raises(RuntimeError, match="audit DB down"):
            client.post(
                f"/api/v1/collaborators/{collab.id}/reviews",
                headers={"Authorization": f"Bearer {token}"},
                json={"rating": 5},
            )
        session_mock.commit.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_audit_repository, None)
