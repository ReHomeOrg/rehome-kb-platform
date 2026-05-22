"""Unit tests для GET /api/v1/admin/audit-log (#237, keyset cursor #343)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.articles.cursor import decode_cursor, encode_cursor
from src.api.audit.models import AuditLog
from src.api.audit.repository import get_audit_repository
from src.api.main import app

# ---------------------------------------------------------------------------
# Router endpoint


def _make_row(
    *,
    actor_sub: str = "actor-1",
    action: str = "article.read",
    resource_type: str = "article",
    resource_id: str | None = "art-1",
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> AuditLog:
    row = AuditLog(
        actor_sub=actor_sub,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        audit_metadata=metadata or {"k": "v"},
    )
    row.id = uuid4()
    row.created_at = created_at or datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    return row


@pytest.fixture
def repo_mock() -> Iterator[AsyncMock]:
    """Override AuditRepository — мы тестируем router, не storage."""
    mock_keyset = AsyncMock(return_value=([], False))

    class _FakeRepo:
        def __init__(self) -> None:
            self.list_records_keyset = mock_keyset

    app.dependency_overrides[get_audit_repository] = lambda: _FakeRepo()
    yield mock_keyset
    app.dependency_overrides.pop(get_audit_repository, None)


def test_anon_returns_401(client: TestClient) -> None:
    resp = client.get("/api/v1/admin/audit-log")
    assert resp.status_code == 401


def test_tenant_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_staff_support_only_returns_403(
    client: TestClient,
    make_jwt: Callable[..., str],
) -> None:
    """staff_support имеет STAFF но не LEGAL → 403."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_staff_admin_returns_200(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"] == []
    assert body["pagination"]["has_more"] is False
    assert body["pagination"]["cursor_next"] is None
    # Keyset не поддерживает backward navigation — cursor_prev всегда null.
    assert body["pagination"]["cursor_prev"] is None
    assert body["pagination"]["total_estimate"] == 0


def test_staff_legal_returns_200(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    """staff_legal = LEGAL без STAFF — OpenAPI говорит «staff_admin или staff_legal»."""
    token = make_jwt(roles=["staff_legal"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_row_projection_maps_to_openapi_shape(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    """actor_sub → actor_id, resource_type → entity_type, created_at → ts."""
    row = _make_row(
        actor_sub="user-uuid-1",
        action="article.read",
        resource_type="article",
        resource_id="slug-x",
        metadata={"slug": "slug-x"},
    )
    repo_mock.return_value = ([row], False)

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert len(body["data"]) == 1
    entry = body["data"][0]
    assert entry["actor_id"] == "user-uuid-1"
    assert entry["entity_type"] == "article"
    assert entry["entity_id"] == "slug-x"
    assert entry["action"] == "article.read"
    assert entry["ts"].startswith("2026-05-01T12:00:00")
    assert entry["details"] == {"slug": "slug-x"}
    # Honest stub fields:
    assert entry["severity"] == "info"
    assert entry["actor_type"] is None
    assert entry["actor_role"] is None
    assert entry["ip"] is None
    assert entry["user_agent"] is None
    assert entry["request_id"] is None


def test_filter_params_passed_to_repo(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    """`actor_id` / `entity_type` / `entity_id` / `from` / `to` → repo kwargs."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        params={
            "actor_id": "user-1",
            "action": "article.read",
            "entity_type": "article",
            "entity_id": "slug-x",
            "from": "2026-05-01T00:00:00Z",
            "to": "2026-05-31T23:59:59Z",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    kwargs = repo_mock.call_args.kwargs
    assert kwargs["actor_sub"] == "user-1"
    assert kwargs["resource_type"] == "article"
    assert kwargs["resource_id"] == "slug-x"
    assert kwargs["action"] == "article.read"
    assert kwargs["since"].year == 2026
    assert kwargs["until"].month == 5


def test_severity_filter_accepted_but_no_op(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    """`severity` accept'ится но не передаётся в repo — honest stub."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        params={"severity": "critical"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    kwargs = repo_mock.call_args.kwargs
    # severity не присутствует среди repo params (нет column).
    assert "severity" not in kwargs


def test_invalid_severity_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        params={"severity": "fatal"},  # not in enum
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_pagination_has_more_returns_cursor_next(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    """has_more=True ⇒ cursor_next encoded из (created_at, id) последней row."""
    last_row = _make_row(action="a-last")
    rows = [_make_row(action=f"a-{i}") for i in range(2)] + [last_row]
    # Repo возвращает (rows[:limit], has_more=True) — здесь limit=3, всё видимо.
    repo_mock.return_value = (rows, True)

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        params={"limit": 3},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert len(body["data"]) == 3
    assert body["pagination"]["has_more"] is True
    assert body["pagination"]["cursor_next"] is not None
    decoded_dt, decoded_id = decode_cursor(body["pagination"]["cursor_next"])
    assert decoded_id == last_row.id
    assert decoded_dt == last_row.created_at
    # cursor_prev keyset не поддерживается — всегда null.
    assert body["pagination"]["cursor_prev"] is None
    # total_estimate = len(rows) + 1 (есть ещё одна страница).
    assert body["pagination"]["total_estimate"] == 4


def test_pagination_no_more_no_cursor_next(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    rows = [_make_row(action=f"a-{i}") for i in range(2)]
    repo_mock.return_value = (rows, False)

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        params={"limit": 50},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert body["pagination"]["has_more"] is False
    assert body["pagination"]["cursor_next"] is None
    assert body["pagination"]["total_estimate"] == 2


def test_invalid_cursor_returns_400(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    """Битый opaque cursor → 400 (InvalidCursorError)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        params={"cursor": "not-valid-base64-payload!!!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_cursor_passes_decoded_tuple_to_repo(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    """?cursor=... → decode → repo.list_records_keyset(cursor=(dt, uuid))."""
    cursor_dt = datetime(2026, 5, 15, 10, 0, tzinfo=UTC)
    cursor_id = uuid4()
    cursor_str = encode_cursor(cursor_dt, cursor_id)

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        params={"cursor": cursor_str, "limit": 25},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    kwargs = repo_mock.call_args.kwargs
    assert kwargs["cursor"] == (cursor_dt, cursor_id)
    # +1 overshoot живёт в repo, не в router'е.
    assert kwargs["limit"] == 25


def test_no_cursor_passes_none_to_repo(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    """Без `?cursor` → repo.list_records_keyset(cursor=None)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    kwargs = repo_mock.call_args.kwargs
    assert kwargs["cursor"] is None


def test_limit_over_max_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    """limit > 500 (OpenAPI maximum) → 422."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        params={"limit": 1000},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
