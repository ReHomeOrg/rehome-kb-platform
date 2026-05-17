"""Unit tests для collaborators router — 5 CRUD endpoints."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.collaborators.models import Collaborator
from src.api.collaborators.repository import (
    CollaboratorRepository,
    get_collaborator_repository,
)
from src.api.db import get_session
from src.api.main import app


def _make_collab(
    *,
    group: str = "D",
    type_: str = "management_company",
    status: str = "ACTIVE",
) -> Collaborator:
    c = Collaborator()
    c.id = uuid4()
    c.name = "Test УК"
    c.brand_name = None
    c.type = type_
    c.financial_group = group
    c.status = status
    c.legal_entity_type = "legal_entity"
    c.inn = None
    c.ogrn = None
    c.kpp = None
    c.service_area = "Москва"
    c.working_hours = "24/7"
    c.website = None
    c.responsible_internal = None
    c.contract_document_id = None
    c.fallback_collaborator_id = None
    c.rating = None
    c.contacts = []
    c.financial_terms = {}
    c.api_integration = {}
    c.sla = {}
    c.counterparty_check = {}
    c.onboarding_source = "staff_invite"
    c.audit_log = []
    c.created_at = datetime(2026, 5, 16, tzinfo=UTC)
    c.updated_at = datetime(2026, 5, 16, tzinfo=UTC)
    return c


@pytest.fixture
def list_mock() -> AsyncMock:
    return AsyncMock(return_value=([], False))


@pytest.fixture
def get_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def create_mock() -> AsyncMock:
    async def _populate_defaults(c: Collaborator) -> Collaborator:
        # Симулирует БД-defaults для id/created_at/updated_at/audit_log,
        # которые на реальной БД заполняются server-side.
        if c.id is None:
            c.id = uuid4()
        if c.created_at is None:
            c.created_at = datetime(2026, 5, 16, tzinfo=UTC)
        if c.updated_at is None:
            c.updated_at = datetime(2026, 5, 16, tzinfo=UTC)
        if c.audit_log is None:
            c.audit_log = []
        if c.onboarding_source is None:
            c.onboarding_source = "staff_invite"
        return c

    return AsyncMock(side_effect=_populate_defaults)


@pytest.fixture
def update_mock() -> AsyncMock:
    async def _passthrough(
        c: Collaborator,
        updates: dict[str, Any],
        **_kwargs: Any,
    ) -> Collaborator:
        # **_kwargs swallows `jsonb_fields` and similar repository kwargs —
        # они не имеют side effect в моке.
        for k, v in updates.items():
            setattr(c, k, v)
        return c

    return AsyncMock(side_effect=_passthrough)


@pytest.fixture
def archive_mock() -> AsyncMock:
    async def _set_archived(c: Collaborator) -> Collaborator:
        c.status = "ARCHIVED"
        return c

    return AsyncMock(side_effect=_set_archived)


@pytest.fixture
def override_repo(
    list_mock: AsyncMock,
    get_mock: AsyncMock,
    create_mock: AsyncMock,
    update_mock: AsyncMock,
    archive_mock: AsyncMock,
) -> Iterator[dict[str, AsyncMock]]:
    repo = CollaboratorRepository.__new__(CollaboratorRepository)
    repo.list_filtered = list_mock  # type: ignore[method-assign]
    repo.get_by_id = get_mock  # type: ignore[method-assign]
    repo.create = create_mock  # type: ignore[method-assign]
    repo.update_fields = update_mock  # type: ignore[method-assign]
    repo.archive = archive_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_collaborator_repository] = lambda: repo
    yield {
        "list": list_mock,
        "get": get_mock,
        "create": create_mock,
        "update": update_mock,
        "archive": archive_mock,
    }
    app.dependency_overrides.pop(get_collaborator_repository, None)


@pytest.fixture
def audit_mock() -> Iterator[AsyncMock]:
    record = AsyncMock()
    fake = MagicMock(spec=AuditRepository)
    fake.record = record
    app.dependency_overrides[get_audit_repository] = lambda: fake
    yield record
    app.dependency_overrides.pop(get_audit_repository, None)


@pytest.fixture
def session_mock() -> Iterator[MagicMock]:
    """Mock session с commit() — нужен для POST/PATCH/DELETE."""
    fake = MagicMock()
    fake.commit = AsyncMock()

    async def _yield() -> Any:
        yield fake

    app.dependency_overrides[get_session] = _yield
    yield fake
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# GET /collaborators (list)


def test_list_returns_200_for_guest(
    client: TestClient, override_repo: dict[str, AsyncMock]
) -> None:
    """Гость может вызвать list — но видит только D-группу (по фильтру в repo)."""
    resp = client.get("/api/v1/collaborators")
    assert resp.status_code == 200


def test_list_guest_uses_only_group_d(
    client: TestClient, override_repo: dict[str, AsyncMock]
) -> None:
    """ADR-0014 §3: guest → {'D'}."""
    client.get("/api/v1/collaborators")
    allowed: frozenset[str] = override_repo["list"].call_args.args[0]
    assert allowed == frozenset({"D"})


def test_list_staff_sees_all_groups(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    client.get("/api/v1/collaborators", headers={"Authorization": f"Bearer {token}"})
    allowed: frozenset[str] = override_repo["list"].call_args.args[0]
    assert allowed == frozenset({"A", "B", "C", "D"})


def test_list_type_filter(client: TestClient, override_repo: dict[str, AsyncMock]) -> None:
    client.get("/api/v1/collaborators?type=management_company")
    assert override_repo["list"].call_args.kwargs["type_filter"] == "management_company"


def test_list_invalid_type_returns_422(
    client: TestClient, override_repo: dict[str, AsyncMock]
) -> None:
    resp = client.get("/api/v1/collaborators?type=nonexistent")
    assert resp.status_code == 422


def test_list_invalid_status_returns_422(
    client: TestClient, override_repo: dict[str, AsyncMock]
) -> None:
    resp = client.get("/api/v1/collaborators?status=NOPE")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /collaborators/{id}


def test_detail_guest_d_collaborator_returns_public_schema(
    client: TestClient, override_repo: dict[str, AsyncMock]
) -> None:
    """Гость видит D-коллаборанта, но без юр.реквизитов/financial_terms."""
    c = _make_collab(group="D")
    override_repo["get"].return_value = c
    resp = client.get(f"/api/v1/collaborators/{c.id}")
    assert resp.status_code == 200
    body = resp.json()
    # Public schema — нет name/inn/contacts/etc.
    assert "name" not in body
    assert "inn" not in body
    assert "contacts" not in body
    assert "audit_log" not in body
    # Видимые поля
    assert body["type"] == "management_company"
    assert body["financial_group"] == "D"


def test_detail_staff_sees_internal_schema(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """staff_support видит юр.данные + контакты, но не audit_log."""
    c = _make_collab(group="A", type_="payment_partner")
    c.name = "ООО Банк-партнёр"
    c.inn = "1234567890"
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/collaborators/{c.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "ООО Банк-партнёр"
    assert body["inn"] == "1234567890"
    assert "audit_log" not in body


def test_detail_admin_sees_audit_log(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """staff_admin имеет STAFF + LEGAL → CollaboratorAdmin schema с audit_log."""
    c = _make_collab(group="A", type_="payment_partner")
    c.audit_log = [{"actor": "x", "action": "created", "ts": "2026-05-16T00:00:00Z"}]
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/collaborators/{c.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "audit_log" in body
    assert body["audit_log"][0]["actor"] == "x"


def test_detail_returns_404_when_repo_returns_none(
    client: TestClient, override_repo: dict[str, AsyncMock]
) -> None:
    """ADR-0014 §3 404 mask — out-of-scope = not found."""
    override_repo["get"].return_value = None
    resp = client.get(f"/api/v1/collaborators/{uuid4()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /collaborators


def test_create_anon_returns_403(client: TestClient, override_repo: dict[str, AsyncMock]) -> None:
    """Anon → PUBLIC scope, STAFF required → 403 (не 401, поскольку
    require_access_level признаёт guest'а authenticated as PUBLIC)."""
    resp = client.post(
        "/api/v1/collaborators",
        json={"name": "x", "type": "management_company", "service_area": "Москва"},
    )
    assert resp.status_code == 403


def test_create_tenant_returns_403(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/collaborators",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "x", "type": "management_company", "service_area": "Москва"},
    )
    assert resp.status_code == 403


def test_create_d_collaborator_auto_active(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """ТЗ §3.10.1: D-группа auto-ACTIVE без явного указания."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/collaborators",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Test УК",
            "type": "management_company",
            "service_area": "Москва",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "ACTIVE"
    assert body["financial_group"] == "D"


def test_create_non_d_stays_draft(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/collaborators",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Cleaning Co",
            "type": "cleaning",
            "service_area": "Москва",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "DRAFT"
    assert resp.json()["financial_group"] == "B"


def test_create_type_other_requires_explicit_group(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """type='other' без financial_group → 422."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/collaborators",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "X", "type": "other", "service_area": "Москва"},
    )
    assert resp.status_code == 422


def test_create_invariant_violation_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Explicit financial_group противоречит type — 422."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/collaborators",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "X",
            "type": "management_company",  # должна быть D
            "financial_group": "B",  # explicit conflict
            "service_area": "Москва",
        },
    )
    assert resp.status_code == 422


def test_create_writes_audit(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/collaborators",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Cleaning Co",
            "type": "cleaning",
            "service_area": "Москва",
        },
    )
    assert resp.status_code == 201
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "collaborator.created"
    assert kwargs["resource_type"] == "collaborator"
    assert kwargs["metadata"]["type"] == "cleaning"
    assert kwargs["metadata"]["financial_group"] == "B"
    session_mock.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# PATCH /collaborators/{id}


def test_patch_anon_returns_403(client: TestClient, override_repo: dict[str, AsyncMock]) -> None:
    resp = client.patch(f"/api/v1/collaborators/{uuid4()}", json={"name": "y"})
    assert resp.status_code == 403


def test_patch_returns_404_when_not_found(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    override_repo["get"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/collaborators/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "y"},
    )
    assert resp.status_code == 404


def test_patch_updates_fields_and_audits(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    c = _make_collab(group="B", type_="cleaning")
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/collaborators/{c.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "New name", "working_hours": "10-22"},
    )
    assert resp.status_code == 200, resp.text
    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["action"] == "collaborator.updated"
    assert "name" in audit_mock.call_args.kwargs["metadata"]["updated_fields"]


# ---------------------------------------------------------------------------
# DELETE /collaborators/{id}


def test_delete_anon_returns_403(client: TestClient, override_repo: dict[str, AsyncMock]) -> None:
    resp = client.delete(f"/api/v1/collaborators/{uuid4()}")
    assert resp.status_code == 403


def test_delete_archives_and_audits(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    c = _make_collab(group="D", status="ACTIVE")
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/collaborators/{c.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "collaborator.archived"
    assert kwargs["metadata"]["previous_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# POST /collaborators/{id}/activate (Slice 2)


def test_activate_anon_returns_403(client: TestClient, override_repo: dict[str, AsyncMock]) -> None:
    resp = client.post(f"/api/v1/collaborators/{uuid4()}/activate")
    assert resp.status_code == 403


def test_activate_d_group_from_draft_succeeds(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    c = _make_collab(group="D", status="DRAFT")
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{c.id}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "collaborator.activated"
    assert kwargs["metadata"]["previous_status"] == "DRAFT"


def test_activate_a_group_without_clean_check_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """A-группа без CLEAN counterparty_check → 422 со списком violations."""
    c = _make_collab(group="A", type_="payment_partner", status="DRAFT")
    c.counterparty_check = {"result": "YELLOW"}
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{c.id}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    body = resp.json()
    violations = body["detail"]["violations"]
    fields = {v["field"] for v in violations}
    assert "counterparty_check.result" in fields
    audit_mock.assert_not_awaited()


def test_activate_already_active_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    c = _make_collab(group="D", status="ACTIVE")
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{c.id}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_activate_not_found_returns_404(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    override_repo["get"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{uuid4()}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /collaborators/{id}/suspend (Slice 2)


def test_suspend_anon_returns_403(client: TestClient, override_repo: dict[str, AsyncMock]) -> None:
    resp = client.post(
        f"/api/v1/collaborators/{uuid4()}/suspend",
        json={"reason": "просрочка проверки"},
    )
    assert resp.status_code == 403


def test_suspend_active_succeeds_with_reason(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    c = _make_collab(group="A", status="ACTIVE")
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{c.id}/suspend",
        headers={"Authorization": f"Bearer {token}"},
        json={"reason": "просрочка проверки контрагента"},
    )
    assert resp.status_code == 200, resp.text
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "collaborator.suspended"
    assert kwargs["metadata"]["reason"] == "просрочка проверки контрагента"
    assert kwargs["metadata"]["previous_status"] == "ACTIVE"


def test_suspend_with_until_passed_to_audit(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    c = _make_collab(group="A", status="ACTIVE")
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{c.id}/suspend",
        headers={"Authorization": f"Bearer {token}"},
        json={"reason": "тех. работы партнёра", "until": "2026-06-01"},
    )
    assert resp.status_code == 200
    assert audit_mock.call_args.kwargs["metadata"]["until"] == "2026-06-01"


def test_suspend_missing_reason_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{uuid4()}/suspend",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert resp.status_code == 422  # Pydantic validation fail


def test_suspend_non_active_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """Suspend из DRAFT — 422 (transition не разрешён)."""
    c = _make_collab(group="D", status="DRAFT")
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{c.id}/suspend",
        headers={"Authorization": f"Bearer {token}"},
        json={"reason": "x"},
    )
    assert resp.status_code == 422
    body = resp.json()
    fields = {v["field"] for v in body["detail"]["violations"]}
    assert "status" in fields


def test_suspend_not_found_returns_404(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    override_repo["get"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/collaborators/{uuid4()}/suspend",
        headers={"Authorization": f"Bearer {token}"},
        json={"reason": "x"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /collaborators/onboarding (Slice 3 — public, rate-limit)


@pytest.fixture(autouse=True)
def _reset_rl() -> None:
    """Reset rate-limiter между tests'ами чтобы они не влияли друг на друга."""
    from src.api.collaborators.ratelimit import reset_global_limiter

    reset_global_limiter()


def _onboard_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "ООО Новый партнёр",
        "type": "cleaning",
        "service_area": "Москва",
        "contact": {"phone": "+7 (495) 123-45-67"},
    }
    payload.update(overrides)
    return payload


def test_onboarding_creates_pending_review(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
) -> None:
    """Public endpoint без auth → PENDING_REVIEW, financial_group auto-derived."""
    resp = client.post("/api/v1/collaborators/onboarding", json=_onboard_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "PENDING_REVIEW"
    assert "id" in body
    assert "получена" in body["message"].lower()
    # Anti-enumeration: response не возвращает payload поля.
    assert "name" not in body
    assert "inn" not in body
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "collaborator.onboarded"
    assert kwargs["metadata"]["source"] == "form"
    assert "ip_hash" in kwargs["metadata"]
    # actor_sub starts with anon: (no auth).
    assert kwargs["actor_sub"].startswith("anon:")


def test_onboarding_other_type_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
) -> None:
    """ADR-0015 §6: type='other' через self-form запрещён."""
    resp = client.post(
        "/api/v1/collaborators/onboarding",
        json=_onboard_payload(type="other"),
    )
    assert resp.status_code == 422


def test_onboarding_missing_contact_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
) -> None:
    """ContactEntry без phone/email/messenger → 422."""
    payload = _onboard_payload(contact={"emergency_channel": False})
    resp = client.post("/api/v1/collaborators/onboarding", json=payload)
    assert resp.status_code == 422


def test_onboarding_invalid_inn_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
) -> None:
    """INN regex — 10 или 12 цифр."""
    resp = client.post(
        "/api/v1/collaborators/onboarding",
        json=_onboard_payload(inn="not-a-number"),
    )
    assert resp.status_code == 422


def test_onboarding_rate_limit_429(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
) -> None:
    """5 запросов проходят, 6-й — 429."""
    for _ in range(5):
        resp = client.post("/api/v1/collaborators/onboarding", json=_onboard_payload())
        assert resp.status_code == 201
    # 6th — should be 429.
    resp = client.post("/api/v1/collaborators/onboarding", json=_onboard_payload())
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_onboarding_persists_portal_access_history(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
) -> None:
    """Initial history entry с reason='initial' + requested level."""
    resp = client.post(
        "/api/v1/collaborators/onboarding",
        json=_onboard_payload(portal_access_level_requested="FULL"),
    )
    assert resp.status_code == 201
    # Captured collaborator object из create_mock side_effect.
    created_collab = override_repo["create"].call_args.args[0]
    assert created_collab.portal_access_level == "NONE"
    history = created_collab.portal_access_history
    assert len(history) == 1
    assert history[0]["from"] is None
    assert history[0]["to"] == "NONE"
    assert history[0]["requested"] == "FULL"
    assert history[0]["reason"] == "initial"


# ---------------------------------------------------------------------------
# PUT /collaborators/{id}/portal-access (Slice 3)


def test_portal_access_anon_returns_403(
    client: TestClient, override_repo: dict[str, AsyncMock]
) -> None:
    resp = client.put(
        f"/api/v1/collaborators/{uuid4()}/portal-access",
        json={"portal_access_level": "LIGHT"},
    )
    assert resp.status_code == 403


def test_portal_access_demote_no_reason_ok(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """Понижение (LIGHT → NONE) — reason необязателен."""
    c = _make_collab(group="B", type_="cleaning", status="ACTIVE")
    c.portal_access_level = "LIGHT"
    c.portal_access_history = []
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.put(
        f"/api/v1/collaborators/{c.id}/portal-access",
        headers={"Authorization": f"Bearer {token}"},
        json={"portal_access_level": "NONE"},
    )
    assert resp.status_code == 200, resp.text
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "collaborator.portal_access.changed"
    assert kwargs["metadata"]["from"] == "LIGHT"
    assert kwargs["metadata"]["to"] == "NONE"


def test_portal_access_promote_without_reason_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """Повышение (NONE → LIGHT) — reason обязателен (ТЗ §10.8.1)."""
    c = _make_collab(group="B", type_="cleaning", status="ACTIVE")
    c.portal_access_level = "NONE"
    c.portal_access_history = []
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.put(
        f"/api/v1/collaborators/{c.id}/portal-access",
        headers={"Authorization": f"Bearer {token}"},
        json={"portal_access_level": "LIGHT"},
    )
    assert resp.status_code == 422


def test_portal_access_promote_with_reason_ok(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    c = _make_collab(group="B", type_="cleaning", status="ACTIVE")
    c.portal_access_level = "NONE"
    c.portal_access_history = []
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.put(
        f"/api/v1/collaborators/{c.id}/portal-access",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "portal_access_level": "FULL",
            "reason": "approved after operator review",
        },
    )
    assert resp.status_code == 200
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["metadata"]["reason"] == "approved after operator review"


def test_portal_access_no_op_returns_200_no_audit(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """Установка того же level — idempotent, history не растёт."""
    c = _make_collab(group="B", type_="cleaning", status="ACTIVE")
    c.portal_access_level = "LIGHT"
    c.portal_access_history = []
    override_repo["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.put(
        f"/api/v1/collaborators/{c.id}/portal-access",
        headers={"Authorization": f"Bearer {token}"},
        json={"portal_access_level": "LIGHT"},
    )
    assert resp.status_code == 200
    audit_mock.assert_not_awaited()


def test_portal_access_not_found_returns_404(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    override_repo["get"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.put(
        f"/api/v1/collaborators/{uuid4()}/portal-access",
        headers={"Authorization": f"Bearer {token}"},
        json={"portal_access_level": "NONE"},
    )
    assert resp.status_code == 404
