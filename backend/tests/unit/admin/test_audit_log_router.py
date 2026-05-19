"""Unit tests для GET /api/v1/admin/audit-log (#237)."""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.admin.audit_log_router import _decode_cursor, _encode_cursor
from src.api.audit.models import AuditLog
from src.api.audit.repository import get_audit_repository
from src.api.main import app

# ---------------------------------------------------------------------------
# Pure: cursor encode/decode


def test_decode_cursor_empty_returns_zero() -> None:
    assert _decode_cursor(None) == 0
    assert _decode_cursor("") == 0


def test_encode_decode_roundtrip() -> None:
    for offset in (0, 1, 50, 1234, 999999):
        assert _decode_cursor(_encode_cursor(offset)) == offset


def test_decode_cursor_invalid_raises_422() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _decode_cursor("not-base64-!@#$")
    assert exc.value.status_code == 422


def test_decode_cursor_negative_raises_422() -> None:
    from fastapi import HTTPException

    bad = base64.urlsafe_b64encode(b"-5").decode("ascii")
    with pytest.raises(HTTPException) as exc:
        _decode_cursor(bad)
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# Router endpoint


def _make_row(
    *,
    actor_sub: str = "actor-1",
    action: str = "article.read",
    resource_type: str = "article",
    resource_id: str | None = "art-1",
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    row = AuditLog(
        actor_sub=actor_sub,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        audit_metadata=metadata or {"k": "v"},
    )
    row.id = uuid4()
    row.created_at = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    return row


@pytest.fixture
def repo_mock() -> Iterator[AsyncMock]:
    """Override AuditRepository — мы тестируем router, не storage."""
    mock_list = AsyncMock(return_value=[])

    class _FakeRepo:
        def __init__(self) -> None:
            self.list_records = mock_list

    app.dependency_overrides[get_audit_repository] = lambda: _FakeRepo()
    yield mock_list
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
    assert body["pagination"]["cursor_prev"] is None


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
    repo_mock.return_value = [row]

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


def test_pagination_has_more_when_limit_exceeded(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    """limit=2 + repo returns 3 (limit+1) → has_more=True + cursor_next set."""
    rows = [_make_row(action=f"a-{i}") for i in range(3)]
    repo_mock.return_value = rows

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        params={"limit": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["pagination"]["has_more"] is True
    assert body["pagination"]["cursor_next"] is not None
    assert _decode_cursor(body["pagination"]["cursor_next"]) == 2  # offset 0 + limit 2


def test_invalid_cursor_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        params={"cursor": "!!!not-base64!!!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_cursor_advances_offset(
    client: TestClient,
    make_jwt: Callable[..., str],
    repo_mock: AsyncMock,
) -> None:
    """Caller'ovsky cursor → offset → repo call с правильным offset."""
    cursor = _encode_cursor(100)
    repo_mock.return_value = []

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/audit-log",
        params={"cursor": cursor, "limit": 25},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    kwargs = repo_mock.call_args.kwargs
    assert kwargs["offset"] == 100
    # limit+1 для has_more detection.
    assert kwargs["limit"] == 26


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
