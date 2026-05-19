"""Router tests для /api/v1/admin/security-incidents* (#231)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.admin.security_incidents_models import SecurityIncident
from src.api.admin.security_incidents_repository import (
    InvalidIncidentTransitionError,
    SecurityIncidentRepository,
    get_security_incident_repository,
)
from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.db import get_session
from src.api.main import app


def _make_incident(**over: Any) -> SecurityIncident:
    inc = SecurityIncident()
    inc.id = uuid4()
    inc.incident_type = "access_violation"
    inc.severity = "medium"
    inc.status = "OPEN"
    inc.detected_at = datetime(2026, 5, 20, tzinfo=UTC)
    inc.detected_by = "audit"
    inc.affected_resources = []
    inc.rkn_notification_required = False
    inc.rkn_notified_at = None
    inc.resolution_note = None
    inc.resolved_at = None
    inc.created_at = datetime(2026, 5, 20, tzinfo=UTC)
    inc.updated_at = datetime(2026, 5, 20, tzinfo=UTC)
    for k, v in over.items():
        setattr(inc, k, v)
    return inc


@pytest.fixture
def list_mock() -> AsyncMock:
    return AsyncMock(return_value=([], False))


@pytest.fixture
def get_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def update_mock() -> AsyncMock:
    async def _passthrough(inc: SecurityIncident, **kwargs: Any) -> SecurityIncident:
        for k, v in kwargs.items():
            if v is not None:
                setattr(inc, k, v)
        return inc

    return AsyncMock(side_effect=_passthrough)


@pytest.fixture
def override_repo(
    list_mock: AsyncMock,
    get_mock: AsyncMock,
    update_mock: AsyncMock,
) -> Iterator[dict[str, AsyncMock]]:
    repo = SecurityIncidentRepository.__new__(SecurityIncidentRepository)
    repo.list_filtered = list_mock  # type: ignore[method-assign]
    repo.get_by_id = get_mock  # type: ignore[method-assign]
    repo.update = update_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_security_incident_repository] = lambda: repo

    audit_record = AsyncMock()
    audit = MagicMock(spec=AuditRepository)
    audit.record = audit_record
    app.dependency_overrides[get_audit_repository] = lambda: audit

    async def _session() -> Any:
        s = MagicMock()
        s.commit = AsyncMock()
        s.rollback = AsyncMock()
        yield s

    app.dependency_overrides[get_session] = _session

    yield {
        "list": list_mock,
        "get": get_mock,
        "update": update_mock,
        "audit": audit_record,
    }
    app.dependency_overrides.pop(get_security_incident_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# Auth gating


def test_list_anon_returns_401(client: TestClient, override_repo: dict[str, AsyncMock]) -> None:
    resp = client.get("/api/v1/admin/security-incidents")
    assert resp.status_code == 401


def test_list_tenant_returns_403(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/security-incidents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_list_staff_support_returns_403(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """staff_support без LEGAL → 403 (security registry — legal-tier)."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/security-incidents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /admin/security-incidents


def test_list_staff_admin_returns_200_empty(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/security-incidents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["pagination"]["has_more"] is False


def test_list_returns_incidents(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    inc = _make_incident(severity="high", incident_type="brute_force")
    list_mock.return_value = ([inc], False)
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/security-incidents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["severity"] == "high"
    assert body["data"][0]["incident_type"] == "brute_force"


def test_list_passes_severity_filter(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/security-incidents?severity=critical",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert list_mock.call_args.kwargs["severity"] == "critical"


def test_list_passes_status_filter(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/security-incidents?status=INVESTIGATING",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert list_mock.call_args.kwargs["status"] == "INVESTIGATING"


def test_list_invalid_severity_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/security-incidents?severity=BREACH",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_list_returns_cursor_when_has_more(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    list_mock.return_value = ([_make_incident()], True)
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/security-incidents",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert body["pagination"]["has_more"] is True
    assert body["pagination"]["cursor_next"] is not None


def test_list_invalid_cursor_returns_400(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/security-incidents?cursor=NOT-VALID",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /admin/security-incidents/{id}


def test_get_404_when_not_found(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    get_mock.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/security-incidents/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_get_returns_view(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    inc = _make_incident(severity="critical")
    get_mock.return_value = inc
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/security-incidents/{inc.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(inc.id)
    assert body["severity"] == "critical"


# ---------------------------------------------------------------------------
# PATCH /admin/security-incidents/{id}


def test_patch_404_when_not_found(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    get_mock.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/security-incidents/{uuid4()}",
        json={"status": "RESOLVED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_patch_transition_to_resolved_audits(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    update_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    inc = _make_incident(status="INVESTIGATING")
    get_mock.return_value = inc
    token = make_jwt(roles=["staff_admin"], sub="legal-user")
    resp = client.patch(
        f"/api/v1/admin/security-incidents/{inc.id}",
        json={"status": "RESOLVED", "resolution_note": "false positive"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    update_mock.assert_awaited_once()
    audit_kwargs = override_repo["audit"].call_args.kwargs
    assert audit_kwargs["action"] == "admin.security_incident.updated"
    assert audit_kwargs["actor_sub"] == "legal-user"
    assert set(audit_kwargs["metadata"]["updated_fields"]) == {
        "status",
        "resolution_note",
    }


def test_patch_terminal_to_open_returns_409(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    update_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Terminal status → non-terminal → 409 (compliance: reopen = new incident)."""
    inc = _make_incident(status="RESOLVED")
    get_mock.return_value = inc
    update_mock.side_effect = InvalidIncidentTransitionError(
        "Cannot transition from terminal status RESOLVED to non-terminal OPEN"
    )
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/security-incidents/{inc.id}",
        json={"status": "OPEN"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


def test_patch_empty_body_is_noop(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    update_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Empty body → no UPDATE, no audit."""
    inc = _make_incident()
    get_mock.return_value = inc
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/security-incidents/{inc.id}",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    update_mock.assert_not_awaited()
    override_repo["audit"].assert_not_awaited()


def test_patch_rkn_notified_at_passes_through(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    update_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    inc = _make_incident(severity="critical", rkn_notification_required=True)
    get_mock.return_value = inc
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/security-incidents/{inc.id}",
        json={"rkn_notified_at": "2026-05-20T15:00:00Z"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    kwargs = update_mock.call_args.kwargs
    assert kwargs["rkn_notified_at"] is not None


def test_patch_extra_field_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """extra='forbid' — нельзя patch'нуть identity-bound fields."""
    inc = _make_incident()
    get_mock.return_value = inc
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/security-incidents/{inc.id}",
        json={"severity": "low"},  # not in allowed patch fields
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_patch_invalid_status_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    inc = _make_incident()
    get_mock.return_value = inc
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/security-incidents/{inc.id}",
        json={"status": "DELETED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
