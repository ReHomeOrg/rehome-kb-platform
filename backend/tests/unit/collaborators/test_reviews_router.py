"""Router tests для /collaborators/{id}/reviews (Slice 6)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.collaborators.models import Collaborator, CollaboratorReview
from src.api.collaborators.reviews_router import _mask_author
from src.api.db import get_session
from src.api.main import app

# ---------------------------------------------------------------------------
# _mask_author helper


def test_mask_author_none_returns_anon() -> None:
    assert _mask_author(None) == "Аноним"


def test_mask_author_empty_returns_anon() -> None:
    assert _mask_author("") == "Аноним"


def test_mask_author_short_appended_stars() -> None:
    assert _mask_author("И") == "И***"
    assert _mask_author("ИИ") == "ИИ***"


def test_mask_author_long_truncated() -> None:
    assert _mask_author("Иван Иванович") == "Ив***"


# ---------------------------------------------------------------------------
# Endpoints — session-mocked


def _make_collab(group: str = "D") -> Collaborator:
    from decimal import Decimal

    c = Collaborator()
    c.id = uuid4()
    c.financial_group = group
    c.rating = Decimal("4.5")
    return c


def _make_review(coll_id: Any, rating: int = 5, name: str | None = "Иван") -> CollaboratorReview:
    r = CollaboratorReview()
    r.id = uuid4()
    r.collaborator_id = coll_id
    r.author_sub = "user-abc"
    r.author_display_name = name
    r.rating = rating
    r.comment = "Отлично!"
    r.created_at = datetime(2026, 5, 17, tzinfo=UTC)
    return r


@pytest.fixture
def fake_session() -> Iterator[MagicMock]:
    s = MagicMock()
    s.commit = AsyncMock()
    s.flush = AsyncMock()
    s.rollback = AsyncMock()
    s.execute = AsyncMock()
    s.add = MagicMock()

    async def _yield() -> Any:
        yield s

    app.dependency_overrides[get_session] = _yield
    yield s
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def audit_mock() -> Iterator[AsyncMock]:
    record = AsyncMock()
    fake = MagicMock(spec=AuditRepository)
    fake.record = record
    app.dependency_overrides[get_audit_repository] = lambda: fake
    yield record
    app.dependency_overrides.pop(get_audit_repository, None)


def _stub_execute_for(session: MagicMock, *return_values: Any) -> None:
    """Программирует session.execute side_effect — каждый вызов возвращает
    MagicMock с scalar_one_or_none / scalars().all() / scalar_one взятыми
    из return_values."""
    results = []
    for val in return_values:
        r = MagicMock()
        if isinstance(val, list):
            r.scalars = MagicMock(return_value=MagicMock(all=lambda v=val: v))
            r.scalar_one_or_none = MagicMock(return_value=val[0] if val else None)
        else:
            r.scalar_one_or_none = MagicMock(return_value=val)
            r.scalars = MagicMock(return_value=MagicMock(all=lambda v=val: [v]))
        results.append(r)
    session.execute.side_effect = results


# ---------------------------------------------------------------------------
# GET /collaborators/{id}/reviews


def test_list_reviews_404_when_collaborator_not_visible(
    client: TestClient, fake_session: MagicMock
) -> None:
    """Guest на A-collaborator → 404 mask (ADR-0014 §3)."""
    _stub_execute_for(fake_session, None)
    resp = client.get(f"/api/v1/collaborators/{uuid4()}/reviews")
    assert resp.status_code == 404


def test_list_reviews_returns_masked_authors(client: TestClient, fake_session: MagicMock) -> None:
    cid = uuid4()
    collab = _make_collab("D")
    collab.id = cid
    r1 = _make_review(cid, rating=5, name="Иван Петров")
    r2 = _make_review(cid, rating=4, name=None)
    _stub_execute_for(fake_session, collab, [r1, r2])
    resp = client.get(f"/api/v1/collaborators/{cid}/reviews")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["aggregate"]["count"] == 2
    assert body["aggregate"]["avg_rating"] == 4.5
    masked = {item["author_masked"] for item in body["data"]}
    assert "Ив***" in masked
    assert "Аноним" in masked


# ---------------------------------------------------------------------------
# POST /collaborators/{id}/reviews


def test_create_review_anon_returns_401(client: TestClient, fake_session: MagicMock) -> None:
    resp = client.post(
        f"/api/v1/collaborators/{uuid4()}/reviews",
        json={"rating": 5},
    )
    assert resp.status_code == 401


def test_create_review_invalid_rating_returns_422(
    client: TestClient, fake_session: MagicMock, make_jwt: Callable[..., str]
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{uuid4()}/reviews",
        headers={"Authorization": f"Bearer {token}"},
        json={"rating": 7},  # out of range
    )
    assert resp.status_code == 422


def test_create_review_404_when_collaborator_not_visible(
    client: TestClient,
    fake_session: MagicMock,
    audit_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    _stub_execute_for(fake_session, None)
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{uuid4()}/reviews",
        headers={"Authorization": f"Bearer {token}"},
        json={"rating": 5},
    )
    assert resp.status_code == 404


def test_create_review_happy_path_recomputes_rating(
    client: TestClient,
    fake_session: MagicMock,
    audit_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    cid = uuid4()
    collab = _make_collab("D")
    collab.id = cid
    # execute calls (в порядке): collab visible, recompute avg, update.
    _stub_execute_for(fake_session, collab, 4.5, None)
    # Simulate server-side DB defaults (id + created_at) при flush.
    review_id = uuid4()

    async def _flush_with_defaults() -> None:
        for call in fake_session.add.call_args_list:
            obj = call.args[0]
            if isinstance(obj, CollaboratorReview):
                if obj.id is None:
                    obj.id = review_id
                if obj.created_at is None:
                    obj.created_at = datetime(2026, 5, 17, tzinfo=UTC)

    fake_session.flush = AsyncMock(side_effect=_flush_with_defaults)
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{cid}/reviews",
        headers={"Authorization": f"Bearer {token}"},
        json={"rating": 5, "comment": "Хорошо", "author_display_name": "Иван"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rating"] == 5
    assert body["author_masked"] == "Ив***"
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "collaborator.review.created"
    assert kwargs["metadata"]["rating"] == 5
    fake_session.commit.assert_awaited()


def test_create_review_duplicate_returns_409(
    client: TestClient,
    fake_session: MagicMock,
    audit_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """UQ violation → 409."""
    cid = uuid4()
    collab = _make_collab("D")
    collab.id = cid
    _stub_execute_for(fake_session, collab)
    # flush raises на insert (UQ violation).
    fake_session.flush = AsyncMock(side_effect=IntegrityError("x", "y", BaseException("dup")))
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{cid}/reviews",
        headers={"Authorization": f"Bearer {token}"},
        json={"rating": 5},
    )
    assert resp.status_code == 409
    audit_mock.assert_not_awaited()
