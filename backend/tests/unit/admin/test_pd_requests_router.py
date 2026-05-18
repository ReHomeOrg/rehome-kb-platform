"""Router tests для /api/v1/admin/personal-data/requests* (#232)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.admin.pd_requests_models import PersonalDataRequest
from src.api.admin.pd_requests_repository import (
    InvalidPdRequestTransitionError,
    PersonalDataRequestRepository,
    get_pd_request_repository,
)
from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.db import get_session
from src.api.main import app


def _make_request(**over: Any) -> PersonalDataRequest:
    r = PersonalDataRequest()
    r.id = uuid4()
    r.type = "provide"
    r.status = "NEW"
    r.subject_id = uuid4()
    r.subject_email = "subject@example.com"
    r.subject_phone = None
    r.description = "Copy of my data"
    r.assigned_to = None
    r.created_at = datetime(2026, 5, 1, tzinfo=UTC)
    r.due_at = datetime(2026, 5, 31, tzinfo=UTC)
    r.completed_at = None
    r.resolution_note = None
    r.attachments = []
    r.updated_at = datetime(2026, 5, 1, tzinfo=UTC)
    for k, v in over.items():
        setattr(r, k, v)
    return r


@pytest.fixture
def list_mock() -> AsyncMock:
    return AsyncMock(return_value=([], False))


@pytest.fixture
def get_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def update_mock() -> AsyncMock:
    async def _passthrough(req: PersonalDataRequest, **kwargs: Any) -> PersonalDataRequest:
        for k, v in kwargs.items():
            if v is not None:
                setattr(req, k, v)
        return req

    return AsyncMock(side_effect=_passthrough)


@pytest.fixture
def override_repo(
    list_mock: AsyncMock,
    get_mock: AsyncMock,
    update_mock: AsyncMock,
) -> Iterator[dict[str, AsyncMock]]:
    repo = PersonalDataRequestRepository.__new__(PersonalDataRequestRepository)
    repo.list_filtered = list_mock  # type: ignore[method-assign]
    repo.get_by_id = get_mock  # type: ignore[method-assign]
    repo.update = update_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_pd_request_repository] = lambda: repo

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
    app.dependency_overrides.pop(get_pd_request_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# Auth gating


def test_list_anon_returns_401(
    client: TestClient, override_repo: dict[str, AsyncMock]
) -> None:
    resp = client.get("/api/v1/admin/personal-data/requests")
    assert resp.status_code == 401


def test_list_tenant_returns_403(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/personal-data/requests",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_list_staff_support_returns_403(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """staff_support без LEGAL → 403 (ПДн compliance — legal-tier)."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/personal-data/requests",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET list


def test_list_staff_admin_returns_200(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/personal-data/requests",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []


def test_list_returns_request(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    req = _make_request(type="delete", status="NEW")
    list_mock.return_value = ([req], False)
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/personal-data/requests",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert body["data"][0]["type"] == "delete"
    assert body["data"][0]["status"] == "NEW"


def test_list_passes_status_filter(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/personal-data/requests?status=OVERDUE",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert list_mock.call_args.kwargs["status"] == "OVERDUE"


def test_list_passes_type_filter(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/personal-data/requests?type=delete",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert list_mock.call_args.kwargs["type_filter"] == "delete"


def test_list_invalid_type_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/personal-data/requests?type=hack",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_list_cursor_when_has_more(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    list_mock.return_value = ([_make_request()], True)
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/personal-data/requests",
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
        "/api/v1/admin/personal-data/requests?cursor=BROKEN",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /{id}


def test_get_404_when_not_found(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    get_mock.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/personal-data/requests/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_get_returns_view(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    req = _make_request(type="correct")
    get_mock.return_value = req
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/personal-data/requests/{req.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert body["type"] == "correct"
    assert body["id"] == str(req.id)


# ---------------------------------------------------------------------------
# PATCH


def test_patch_404_when_not_found(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    get_mock.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/personal-data/requests/{uuid4()}",
        json={"status": "IN_PROGRESS"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_patch_transition_to_completed_audits(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    update_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    req = _make_request(status="IN_PROGRESS")
    get_mock.return_value = req
    token = make_jwt(roles=["staff_admin"], sub="legal-actor")
    resp = client.patch(
        f"/api/v1/admin/personal-data/requests/{req.id}",
        json={
            "status": "COMPLETED",
            "resolution_note": "Data sent to subject",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    update_mock.assert_awaited_once()
    audit_kwargs = override_repo["audit"].call_args.kwargs
    assert audit_kwargs["action"] == "admin.personal_data_request.updated"
    assert audit_kwargs["actor_sub"] == "legal-actor"
    assert audit_kwargs["metadata"]["subject_id"] == str(req.subject_id)
    assert set(audit_kwargs["metadata"]["updated_fields"]) == {
        "status",
        "resolution_note",
    }


def test_patch_invalid_transition_returns_409(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    update_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """NEW → COMPLETED skip IN_PROGRESS → 409."""
    req = _make_request(status="NEW")
    get_mock.return_value = req
    update_mock.side_effect = InvalidPdRequestTransitionError(
        "Cannot transition from NEW to COMPLETED"
    )
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/personal-data/requests/{req.id}",
        json={"status": "COMPLETED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


def test_patch_status_required(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """OpenAPI: status — required в body."""
    req = _make_request()
    get_mock.return_value = req
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/personal-data/requests/{req.id}",
        json={"resolution_note": "note only"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_patch_invalid_status_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """`NEW` / `OVERDUE` нельзя задать через PATCH (только auto-set)."""
    req = _make_request()
    get_mock.return_value = req
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/personal-data/requests/{req.id}",
        json={"status": "OVERDUE"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_patch_attachments_too_many_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    req = _make_request()
    get_mock.return_value = req
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    too_many = [str(uuid4()) for _ in range(60)]
    resp = client.patch(
        f"/api/v1/admin/personal-data/requests/{req.id}",
        json={"status": "IN_PROGRESS", "attachments": too_many},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_patch_attachments_passthrough(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    update_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    req = _make_request(status="IN_PROGRESS")
    get_mock.return_value = req
    attachments = [str(uuid4()), str(uuid4())]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/personal-data/requests/{req.id}",
        json={"status": "COMPLETED", "attachments": attachments},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    kwargs = update_mock.call_args.kwargs
    assert kwargs["attachments"] is not None
    assert len(kwargs["attachments"]) == 2


def test_patch_extra_field_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """type / subject_id / etc. — identity-bound, не patch'аются."""
    req = _make_request()
    get_mock.return_value = req
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/personal-data/requests/{req.id}",
        json={"status": "IN_PROGRESS", "type": "delete"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
