"""Router tests для ПДн encryption flow (#234, ADR-0018)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit import AuditRepository, get_audit_repository
from src.api.config import Settings
from src.api.db import get_session
from src.api.hr.crypto import encrypt_pii
from src.api.hr.models import HrEmployee
from src.api.hr.repository import HrEmployeeRepository, get_hr_employee_repository
from src.api.main import app


def _make_employee(**over: Any) -> HrEmployee:
    e = HrEmployee()
    e.id = uuid4()
    e.user_id = None
    e.personnel_number = None
    e.full_name = "Иванов И.И."
    e.position = "Engineer"
    e.department = "Eng"
    e.hire_date = date(2024, 1, 15)
    e.termination_date = None
    e.status = "ACTIVE"
    e.contact_info = {}
    e.notes = {}
    e.passport_number_encrypted = None
    e.inn_encrypted = None
    e.snils_encrypted = None
    e.bank_account_encrypted = None
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

    class _FakeSession:
        async def commit(self) -> None:
            pass

    async def _fake_session_dep() -> AsyncIterator[object]:
        yield _FakeSession()

    app.dependency_overrides[get_hr_employee_repository] = lambda: repo
    app.dependency_overrides[get_audit_repository] = lambda: audit
    app.dependency_overrides[get_session] = _fake_session_dep
    yield {**repo_mocks, "audit": audit_record_mock}
    app.dependency_overrides.pop(get_hr_employee_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# POST — encrypt on create, audit pii_updated


def test_create_with_pii_encrypts_and_audits(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """ПДн plaintext → encrypted перед repo.create + audit pii_updated."""
    create_mock = override_deps["create"]

    async def _capture(**kwargs: Any) -> HrEmployee:
        # Repo.create получает encrypted BYTEA values, не plaintext.
        e = _make_employee(**kwargs)
        # Сразу exercise — encrypted columns должны быть bytes (или None).
        for attr in ("passport_number_encrypted", "inn_encrypted"):
            value = getattr(e, attr)
            assert value is None or isinstance(value, bytes)
        return e

    create_mock.side_effect = _capture

    token = make_jwt(roles=["staff_hr"], sub="hr-actor")
    resp = client.post(
        "/api/v1/hr/employees",
        json={
            "full_name": "Иванов И.И.",
            "position": "Engineer",
            "hire_date": "2024-01-15",
            "passport_number": "1234 567890",
            "inn": "770700700007",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    # Response содержит decrypted ПДн.
    body = resp.json()
    assert body["passport_number"] == "1234 567890"
    assert body["inn"] == "770700700007"
    assert body["snils"] is None  # не передан
    # Audit: 2 calls — `created` + `pii_updated` (с именами полей).
    audit_calls = override_deps["audit"].call_args_list
    actions = [c.kwargs["action"] for c in audit_calls]
    assert "hr.employee.created" in actions
    assert "hr.employee.pii_updated" in actions
    # PII audit metadata — fields_set, без values (анти-leak).
    pii_call = next(c for c in audit_calls if c.kwargs["action"] == "hr.employee.pii_updated")
    assert set(pii_call.kwargs["metadata"]["fields_set"]) == {"passport_number", "inn"}
    assert "values" not in pii_call.kwargs["metadata"]


def test_create_without_pii_skips_pii_audit(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """No ПДн в payload → только `created` audit, без `pii_updated`."""
    override_deps["create"].side_effect = lambda **k: _make_employee(**k)
    token = make_jwt(roles=["staff_hr"], sub="hr-1")
    resp = client.post(
        "/api/v1/hr/employees",
        json={
            "full_name": "Петров П.П.",
            "position": "QA",
            "hire_date": "2024-01-15",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    actions = [c.kwargs["action"] for c in override_deps["audit"].call_args_list]
    assert "hr.employee.created" in actions
    assert "hr.employee.pii_updated" not in actions


# ---------------------------------------------------------------------------
# GET — decrypt + audit pii_accessed


def test_get_with_pii_decrypts_and_audits(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    s = Settings()
    emp = _make_employee(
        passport_number_encrypted=encrypt_pii("1234 567890", s),
        inn_encrypted=encrypt_pii("770700700007", s),
    )
    override_deps["get_by_id"].return_value = emp
    token = make_jwt(roles=["staff_hr"], sub="hr-actor")
    resp = client.get(
        f"/api/v1/hr/employees/{emp.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["passport_number"] == "1234 567890"
    assert body["inn"] == "770700700007"
    assert body["snils"] is None
    # Audit: viewed + pii_accessed (потому что non-null поля присутствуют).
    actions = [c.kwargs["action"] for c in override_deps["audit"].call_args_list]
    assert "hr.employee.viewed" in actions
    assert "hr.employee.pii_accessed" in actions


def test_get_without_pii_only_viewed_audit(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Employee без ПДн → `viewed` audit, без `pii_accessed`."""
    emp = _make_employee()  # все ПДн encrypted columns = None
    override_deps["get_by_id"].return_value = emp
    token = make_jwt(roles=["staff_hr"], sub="hr-1")
    resp = client.get(
        f"/api/v1/hr/employees/{emp.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    actions = [c.kwargs["action"] for c in override_deps["audit"].call_args_list]
    assert "hr.employee.viewed" in actions
    assert "hr.employee.pii_accessed" not in actions


# ---------------------------------------------------------------------------
# PATCH — encrypt on update, separate audits, clear via empty string


def test_patch_sets_pii_and_audits(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    emp = _make_employee()

    async def _update(employee_id: Any, *, patch: dict[str, Any]) -> HrEmployee:
        for k, v in patch.items():
            setattr(emp, k, v)
        return emp

    override_deps["update"].side_effect = _update
    token = make_jwt(roles=["staff_hr"], sub="hr-actor")
    resp = client.patch(
        f"/api/v1/hr/employees/{emp.id}",
        json={"passport_number": "9876 543210"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["passport_number"] == "9876 543210"
    actions = [c.kwargs["action"] for c in override_deps["audit"].call_args_list]
    assert "hr.employee.pii_updated" in actions
    # Non-pii update не fired (только ПДн в patch).
    assert "hr.employee.updated" not in actions


def test_patch_clears_pii_via_empty_string(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Empty string в ПДн поле → encrypted column = NULL."""
    s = Settings()
    emp = _make_employee(
        inn_encrypted=encrypt_pii("770700700007", s),
    )

    captured_patch: dict[str, Any] = {}

    async def _update(employee_id: Any, *, patch: dict[str, Any]) -> HrEmployee:
        captured_patch.update(patch)
        for k, v in patch.items():
            setattr(emp, k, v)
        return emp

    override_deps["update"].side_effect = _update
    token = make_jwt(roles=["staff_hr"], sub="hr-1")
    resp = client.patch(
        f"/api/v1/hr/employees/{emp.id}",
        json={"inn": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    # repo получил `inn_encrypted=None` (clearing).
    assert captured_patch.get("inn_encrypted") is None
    assert "inn_encrypted" in captured_patch


def test_patch_mixed_pii_and_regular_fields(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Mixed PATCH — оба audit events (updated + pii_updated)."""
    emp = _make_employee()

    async def _update(employee_id: Any, *, patch: dict[str, Any]) -> HrEmployee:
        for k, v in patch.items():
            setattr(emp, k, v)
        return emp

    override_deps["update"].side_effect = _update
    token = make_jwt(roles=["staff_hr"], sub="hr-1")
    resp = client.patch(
        f"/api/v1/hr/employees/{emp.id}",
        json={"position": "Senior Engineer", "snils": "112-233-445 95"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    actions = [c.kwargs["action"] for c in override_deps["audit"].call_args_list]
    assert "hr.employee.updated" in actions
    assert "hr.employee.pii_updated" in actions
    pii_call = next(
        c
        for c in override_deps["audit"].call_args_list
        if c.kwargs["action"] == "hr.employee.pii_updated"
    )
    assert pii_call.kwargs["metadata"]["fields_set"] == ["snils"]


def test_patch_extra_field_returns_422(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """`passport_number_encrypted` (BYTEA column name) — НЕ valid PATCH field."""
    emp = _make_employee()
    override_deps["get_by_id"].return_value = emp
    token = make_jwt(roles=["staff_hr"], sub="hr-1")
    resp = client.patch(
        f"/api/v1/hr/employees/{emp.id}",
        json={"passport_number_encrypted": "raw bytes"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_patch_pii_too_long_returns_422(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    emp = _make_employee()
    override_deps["get_by_id"].return_value = emp
    token = make_jwt(roles=["staff_hr"], sub="hr-1")
    resp = client.patch(
        f"/api/v1/hr/employees/{emp.id}",
        json={"passport_number": "x" * 100},  # >64
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Scope check — non-HR scope не может видеть ПДн endpoints


def test_staff_admin_blocked_from_pii(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """ADR-0003: staff_admin не имеет HR_RESTRICTED — 403 на GET."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/hr/employees/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
