"""Unit tests для POST /api/v1/admin/audit-log/export (#239)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.admin.audit_log_router import _build_export_url
from src.api.admin.tasks_models import AdminTask
from src.api.admin.tasks_repository import get_admin_task_repository
from src.api.admin.tasks_schemas import AuditLogExportRequest
from src.api.audit.repository import get_audit_repository
from src.api.main import app


def _make_task(
    *,
    type_: str = "audit_log_export",
    status: str = "PENDING",
    actor_sub: str = "admin-uuid",
) -> AdminTask:
    row = AdminTask(type=type_, status=status, actor_sub=actor_sub, params={})
    row.id = uuid4()
    row.created_at = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    return row


@pytest.fixture
def task_repo_mock() -> Iterator[dict[str, AsyncMock]]:
    create = AsyncMock()
    mark_running = AsyncMock()
    mark_completed = AsyncMock()

    class _FakeRepo:
        def __init__(self) -> None:
            self.create = create
            self.mark_running = mark_running
            self.mark_completed = mark_completed
            self.get = AsyncMock(return_value=None)
            self.mark_failed = AsyncMock()

    app.dependency_overrides[get_admin_task_repository] = lambda: _FakeRepo()
    yield {
        "create": create,
        "mark_running": mark_running,
        "mark_completed": mark_completed,
    }
    app.dependency_overrides.pop(get_admin_task_repository, None)


@pytest.fixture
def audit_repo_mock() -> Iterator[AsyncMock]:
    record = AsyncMock()

    class _FakeRepo:
        def __init__(self) -> None:
            self.record = record

    app.dependency_overrides[get_audit_repository] = lambda: _FakeRepo()
    yield record
    app.dependency_overrides.pop(get_audit_repository, None)


# ---------------------------------------------------------------------------
# Pure: URL builder


def test_build_export_url_basic() -> None:
    payload = AuditLogExportRequest.model_validate(
        {
            "from": "2026-05-01T00:00:00Z",
            "to": "2026-05-31T23:59:59Z",
        }
    )
    url = _build_export_url(payload)
    assert url.startswith("/api/v1/audit-log/export.csv?")
    assert "since=2026-05-01" in url
    assert "until=2026-05-31" in url


def test_build_export_url_whitelisted_filters() -> None:
    """Filters: actor_sub / resource_type / resource_id / action / q пропускаются."""
    payload = AuditLogExportRequest.model_validate(
        {
            "from": "2026-05-01T00:00:00Z",
            "to": "2026-05-31T23:59:59Z",
            "filters": {
                "actor_sub": "user-1",
                "resource_type": "article",
                "action": "article.read",
                "q": "slug-x",
            },
        }
    )
    url = _build_export_url(payload)
    assert "actor_sub=user-1" in url
    assert "resource_type=article" in url
    assert "action=article.read" in url
    assert "q=slug-x" in url


def test_build_export_url_drops_unknown_filter_keys() -> None:
    """Anti-injection: unknown filter keys отбрасываются."""
    payload = AuditLogExportRequest.model_validate(
        {
            "from": "2026-05-01T00:00:00Z",
            "to": "2026-05-31T23:59:59Z",
            "filters": {
                "actor_sub": "user-1",
                "malicious": "%26evil%3D1",
                "raw_sql": "SELECT *",
            },
        }
    )
    url = _build_export_url(payload)
    assert "actor_sub=user-1" in url
    assert "malicious" not in url
    assert "raw_sql" not in url


# ---------------------------------------------------------------------------
# Router endpoint RBAC


def test_anon_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/admin/audit-log/export",
        json={"from": "2026-05-01T00:00:00Z", "to": "2026-05-31T23:59:59Z"},
    )
    assert resp.status_code == 401


def test_tenant_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/audit-log/export",
        json={"from": "2026-05-01T00:00:00Z", "to": "2026-05-31T23:59:59Z"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_staff_support_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    """staff_support не имеет LEGAL → 403."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/audit-log/export",
        json={"from": "2026-05-01T00:00:00Z", "to": "2026-05-31T23:59:59Z"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_staff_admin_returns_202(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    task = _make_task()
    task_repo_mock["create"].return_value = task

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/audit-log/export",
        json={"from": "2026-05-01T00:00:00Z", "to": "2026-05-31T23:59:59Z"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["task_id"] == str(task.id)
    assert body["estimated_ready_at"] is None


def test_staff_legal_returns_202(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    task = _make_task()
    task_repo_mock["create"].return_value = task

    token = make_jwt(roles=["staff_legal"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/audit-log/export",
        json={"from": "2026-05-01T00:00:00Z", "to": "2026-05-31T23:59:59Z"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202


def test_missing_required_body_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/audit-log/export",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_invalid_format_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/audit-log/export",
        json={
            "from": "2026-05-01T00:00:00Z",
            "to": "2026-05-31T23:59:59Z",
            "format": "xml",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_task_lifecycle_created_running_completed(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    """create → mark_running → mark_completed (with result_url)."""
    task = _make_task()
    task_repo_mock["create"].return_value = task

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/audit-log/export",
        json={
            "from": "2026-05-01T00:00:00Z",
            "to": "2026-05-31T23:59:59Z",
            "reason": "запрос из РКН №123",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202

    # Task was created с правильными params.
    task_repo_mock["create"].assert_awaited_once()
    create_kwargs = task_repo_mock["create"].call_args.kwargs
    assert create_kwargs["type_"] == "audit_log_export"
    assert create_kwargs["params"]["reason"] == "запрос из РКН №123"
    assert create_kwargs["params"]["format"] == "csv"

    # Lifecycle methods called в правильном порядке.
    task_repo_mock["mark_running"].assert_awaited_once_with(task.id)
    task_repo_mock["mark_completed"].assert_awaited_once()
    completed_kwargs = task_repo_mock["mark_completed"].call_args.kwargs
    assert completed_kwargs["result_url"].startswith("/api/v1/audit-log/export.csv?")

    # Audit trail.
    audit_repo_mock.assert_awaited_once()
    audit_kwargs = audit_repo_mock.call_args.kwargs
    assert audit_kwargs["action"] == "admin.audit_log.exported"
    assert audit_kwargs["metadata"]["reason"] == "запрос из РКН №123"


def test_filters_propagate_to_result_url(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    task = _make_task()
    task_repo_mock["create"].return_value = task

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/audit-log/export",
        json={
            "from": "2026-05-01T00:00:00Z",
            "to": "2026-05-31T23:59:59Z",
            "filters": {"resource_type": "vault_secret", "action": "vault.unlock.failed"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    result_url = task_repo_mock["mark_completed"].call_args.kwargs["result_url"]
    assert "resource_type=vault_secret" in result_url
    assert "action=vault.unlock.failed" in result_url


def test_unknown_filter_keys_ignored_safely(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    """Anti-injection: payload filter с unknown key → не leak'ается в URL."""
    task = _make_task()
    task_repo_mock["create"].return_value = task

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/audit-log/export",
        json={
            "from": "2026-05-01T00:00:00Z",
            "to": "2026-05-31T23:59:59Z",
            "filters": {"injection": "&secret=1", "actor_sub": "x"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    result_url = task_repo_mock["mark_completed"].call_args.kwargs["result_url"]
    assert "injection" not in result_url
    assert "actor_sub=x" in result_url
