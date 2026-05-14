"""Unit tests для audit-log search endpoint (#163)."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit.models import AuditLog
from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.main import app


def _make_record(**over: Any) -> AuditLog:
    r = AuditLog()
    r.id = uuid4()
    r.actor_sub = "user-123"
    r.action = "articles.created"
    r.resource_type = "article"
    r.resource_id = "test-slug"
    r.audit_metadata = {"access_level": "PUBLIC"}
    r.created_at = datetime.now(UTC)
    for k, v in over.items():
        setattr(r, k, v)
    return r


@pytest.fixture
def list_mock() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture
def override_audit_repo(list_mock: AsyncMock) -> Iterator[AsyncMock]:
    repo = AuditRepository.__new__(AuditRepository)
    # `record` нужен для autouse no-op fixture совместимости.
    repo.record = AsyncMock(return_value=None)  # type: ignore[method-assign]
    repo.list_records = list_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_audit_repository] = lambda: repo
    yield list_mock
    app.dependency_overrides.pop(get_audit_repository, None)


# ---------------------------------------------------------------------------
# auth boundary


def test_audit_requires_auth(client: TestClient, override_audit_repo: AsyncMock) -> None:
    resp = client.get("/api/v1/audit-log")
    assert resp.status_code == 401


def test_audit_tenant_403(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Tenant не имеет LEGAL access → 403."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_audit_staff_support_403(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """staff_support имеет STAFF но НЕ LEGAL — 403."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_audit_staff_admin_has_access(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """staff_admin даёт LEGAL access — 200."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# filters + pagination


def test_audit_returns_data_with_pagination_meta(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    list_mock.return_value = [_make_record(), _make_record(action="articles.updated")]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["pagination"] == {"limit": 50, "offset": 0, "count": 2}
    # `metadata` сериализуется (alias from audit_metadata).
    assert body["data"][0]["metadata"] == {"access_level": "PUBLIC"}


def test_audit_filters_passed_to_repo(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log"
        "?actor_sub=user-123"
        "&resource_type=article"
        "&resource_id=test-slug"
        "&action=articles.created"
        "&limit=10&offset=20",
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = list_mock.call_args.kwargs
    assert kwargs["actor_sub"] == "user-123"
    assert kwargs["resource_type"] == "article"
    assert kwargs["resource_id"] == "test-slug"
    assert kwargs["action"] == "articles.created"
    assert kwargs["limit"] == 10
    assert kwargs["offset"] == 20


def test_audit_date_filters(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log?since=2026-01-01T00:00:00Z&until=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = list_mock.call_args.kwargs
    assert kwargs["since"] is not None
    assert kwargs["until"] is not None


def test_audit_invalid_limit_returns_422(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log?limit=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    resp = client.get(
        "/api/v1/audit-log?limit=201",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_audit_invalid_date_returns_422(
    client: TestClient,
    override_audit_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/audit-log?since=not-a-date",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_audit_no_filters_returns_recent_50(
    client: TestClient,
    override_audit_repo: AsyncMock,
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = list_mock.call_args.kwargs
    # Default limit=50, offset=0, остальные filters — None.
    assert kwargs["limit"] == 50
    assert kwargs["offset"] == 0
    assert kwargs["actor_sub"] is None
    assert kwargs["resource_type"] is None


@pytest.mark.asyncio
async def test_repository_list_records_applies_filters() -> None:
    """Repository SQL inspection — verify фильтры попадают в bind params."""
    from unittest.mock import MagicMock

    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = AuditRepository(session)
    await repo.list_records(
        actor_sub="user-x",
        resource_type="article",
        action="articles.created",
        limit=10,
    )
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[object] = []
    for v in compiled.params.values():
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    assert "user-x" in flat
    assert "article" in flat
    assert "articles.created" in flat
