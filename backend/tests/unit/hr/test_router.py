"""Unit tests for kb-hr router (#150)."""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit import AuditRepository, get_audit_repository
from src.api.db import get_session
from src.api.hr.models import HrEmployee
from src.api.hr.repository import HrEmployeeRepository, get_hr_employee_repository
from src.api.main import app


def _make_employee(**over: Any) -> HrEmployee:
    e = HrEmployee()
    e.id = uuid4()
    e.user_id = None
    e.personnel_number = None
    e.full_name = "Иванов Иван Иванович"
    e.position = "Backend Engineer"
    e.department = "Engineering"
    e.hire_date = date(2024, 1, 15)
    e.termination_date = None
    e.status = "ACTIVE"
    e.contact_info = {"email": "ivanov@rehome.one"}
    e.notes = {}
    e.created_at = datetime.now(UTC)
    e.updated_at = datetime.now(UTC)
    e.archived_at = None
    for k, v in over.items():
        setattr(e, k, v)
    return e


@pytest.fixture
def repo_mocks() -> dict[str, AsyncMock]:
    return {
        "get_by_id": AsyncMock(return_value=None),
        "list_active": AsyncMock(return_value=([], False)),
        "create": AsyncMock(),
        "update": AsyncMock(return_value=None),
        "archive": AsyncMock(return_value=False),
    }


@pytest.fixture
def audit_record_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def override_deps(
    repo_mocks: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
) -> Iterator[dict[str, AsyncMock]]:
    repo = HrEmployeeRepository.__new__(HrEmployeeRepository)
    for name, mock in repo_mocks.items():
        setattr(repo, name, mock)
    audit = AuditRepository.__new__(AuditRepository)
    audit.record = audit_record_mock  # type: ignore[method-assign]

    # Fake session с no-op commit (router endpoints call `await
    # session.commit()` после audit records).
    class _FakeSession:
        async def commit(self) -> None:
            pass

    from collections.abc import AsyncIterator

    async def _fake_session_dep() -> AsyncIterator[object]:
        yield _FakeSession()

    app.dependency_overrides[get_hr_employee_repository] = lambda: repo
    app.dependency_overrides[get_audit_repository] = lambda: audit
    app.dependency_overrides[get_session] = _fake_session_dep
    yield repo_mocks
    app.dependency_overrides.pop(get_hr_employee_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# auth boundary


def test_endpoints_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/hr/employees").status_code == 401
    assert client.get(f"/api/v1/hr/employees/{uuid4()}").status_code == 401
    assert client.post("/api/v1/hr/employees", json={}).status_code == 401


def test_list_requires_hr_restricted(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Tenant role не имеет HR_RESTRICTED → 403."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/hr/employees",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_staff_admin_does_not_get_hr_access(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """staff_admin scope не имеет HR_RESTRICTED unless также есть staff_hr.

    Per ADR-0003: HR_RESTRICTED — отдельный access tier. staff_admin
    видит STAFF + LEGAL, но НЕ HR_RESTRICTED.
    """
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/hr/employees",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_staff_hr_has_access(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """staff_hr роль — HR_RESTRICTED tier."""
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/hr/employees",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# list


def test_list_empty(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/hr/employees",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_list_returns_summaries_no_notes(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Summary view — без notes (potentially sensitive HR comments)."""
    override_deps["list_active"].return_value = (
        [_make_employee(notes={"performance_review": "Excellent"})],
        False,
    )
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/hr/employees",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert len(body["data"]) == 1
    item = body["data"][0]
    assert "notes" not in item
    assert "contact_info" not in item


def test_list_include_terminated_param(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    client.get(
        "/api/v1/hr/employees?include_terminated=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert override_deps["list_active"].call_args.kwargs["include_terminated"] is True


def test_list_invalid_cursor_returns_400(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/hr/employees?cursor=!!!malformed!!!",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# get_by_id


def test_get_not_found(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/hr/employees/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_get_audits_view(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """PZ §7 — все просмотры карточек аудитуются."""
    emp = _make_employee()
    override_deps["get_by_id"].return_value = emp
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/hr/employees/{emp.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    audit_record_mock.assert_awaited_once()
    assert audit_record_mock.call_args.kwargs["action"] == "hr.employee.viewed"


# ---------------------------------------------------------------------------
# create


def _valid_create_payload() -> dict[str, Any]:
    return {
        "full_name": "Петров Пётр Петрович",
        "position": "QA Engineer",
        "department": "Engineering",
        "hire_date": "2024-03-01",
    }


def test_create_201(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    emp = _make_employee(full_name="Петров Пётр Петрович")
    override_deps["create"].return_value = emp
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/hr/employees",
        json=_valid_create_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.headers["Location"] == f"/api/v1/hr/employees/{emp.id}"
    audit_record_mock.assert_awaited_once()
    assert audit_record_mock.call_args.kwargs["action"] == "hr.employee.created"


def test_create_missing_required_field(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/hr/employees",
        json={"full_name": "X"},  # position missing
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_create_extra_field_returns_422(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    payload = _valid_create_payload() | {"evil_field": "x"}
    resp = client.post(
        "/api/v1/hr/employees",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_create_invalid_status(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    payload = _valid_create_payload() | {"status": "UNKNOWN"}
    resp = client.post(
        "/api/v1/hr/employees",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# patch


def test_patch_not_found(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/hr/employees/{uuid4()}",
        json={"position": "Senior"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_patch_updates_and_audits(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    override_deps["update"].return_value = _make_employee(position="Senior Backend")
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/hr/employees/{uuid4()}",
        json={"position": "Senior Backend"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    # Patch dict содержит только non-None.
    assert override_deps["update"].call_args.kwargs["patch"] == {"position": "Senior Backend"}
    assert audit_record_mock.call_args.kwargs["action"] == "hr.employee.updated"
    assert audit_record_mock.call_args.kwargs["metadata"]["fields_changed"] == ["position"]


# ---------------------------------------------------------------------------
# delete


def test_delete_not_found(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/hr/employees/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_delete_archives_and_audits(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    override_deps["archive"].return_value = True
    token = make_jwt(roles=["staff_hr"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/hr/employees/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    assert audit_record_mock.call_args.kwargs["action"] == "hr.employee.archived"
