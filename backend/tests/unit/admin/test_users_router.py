"""Router tests для /api/v1/admin/users* (#230)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from src.api.admin.users_models import KbUser
from src.api.admin.users_repository import (
    KbUserRepository,
    get_kb_user_repository,
)
from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.db import get_session
from src.api.main import app


def _make_user(**over: Any) -> KbUser:
    u = KbUser()
    u.id = uuid4()
    u.email = "admin@rehome.one"
    u.full_name = "Иван Иванович"
    u.role = "staff_admin"
    u.permissions = []
    u.status = "ACTIVE"
    u.created_at = datetime(2026, 5, 19, tzinfo=UTC)
    u.updated_at = datetime(2026, 5, 19, tzinfo=UTC)
    u.last_login_at = None
    u.mfa_enabled = False
    for k, v in over.items():
        setattr(u, k, v)
    return u


@pytest.fixture
def list_mock() -> AsyncMock:
    return AsyncMock(return_value=([], False))


@pytest.fixture
def get_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def create_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def update_mock() -> AsyncMock:
    async def _passthrough(user: KbUser, updates: dict[str, Any]) -> KbUser:
        for k, v in updates.items():
            setattr(user, k, v)
        return user

    return AsyncMock(side_effect=_passthrough)


@pytest.fixture
def deactivate_mock() -> AsyncMock:
    async def _set_archived(user: KbUser) -> KbUser:
        user.status = "ARCHIVED"
        return user

    return AsyncMock(side_effect=_set_archived)


@pytest.fixture
def override_repo(
    list_mock: AsyncMock,
    get_mock: AsyncMock,
    create_mock: AsyncMock,
    update_mock: AsyncMock,
    deactivate_mock: AsyncMock,
) -> Iterator[dict[str, AsyncMock]]:
    repo = KbUserRepository.__new__(KbUserRepository)
    repo.list_filtered = list_mock  # type: ignore[method-assign]
    repo.get_by_id = get_mock  # type: ignore[method-assign]
    repo.create = create_mock  # type: ignore[method-assign]
    repo.update_fields = update_mock  # type: ignore[method-assign]
    repo.deactivate = deactivate_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_kb_user_repository] = lambda: repo

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
        "create": create_mock,
        "update": update_mock,
        "deactivate": deactivate_mock,
        "audit": audit_record,
    }
    app.dependency_overrides.pop(get_kb_user_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# Auth gating — same pattern для всех 5 endpoints


def test_list_anon_returns_401(client: TestClient, override_repo: dict[str, AsyncMock]) -> None:
    resp = client.get("/api/v1/admin/users")
    assert resp.status_code == 401


def test_list_tenant_returns_403(
    client: TestClient, override_repo: dict[str, AsyncMock], make_jwt: Callable[..., str]
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_list_staff_support_returns_403(
    client: TestClient, override_repo: dict[str, AsyncMock], make_jwt: Callable[..., str]
) -> None:
    """staff_support без LEGAL → 403."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /admin/users (list)


def test_list_staff_admin_returns_200(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    list_mock.return_value = ([_make_user()], False)
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["email"] == "admin@rehome.one"
    assert body["pagination"]["has_more"] is False


def test_list_passes_role_filter(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/users?role=staff_legal",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert list_mock.call_args.kwargs["role"] == "staff_legal"


def test_list_passes_status_filter(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/users?status=SUSPENDED",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert list_mock.call_args.kwargs["status"] == "SUSPENDED"


def test_list_returns_cursor_when_has_more(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    list_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    list_mock.return_value = ([_make_user()], True)
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    assert body["pagination"]["has_more"] is True
    assert body["pagination"]["cursor_next"] is not None


def test_list_invalid_role_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/users?role=hacker",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /admin/users


def _create_body(**over: Any) -> dict[str, Any]:
    base = {
        "email": "new@rehome.one",
        "full_name": "Новый Сотрудник",
        "role": "staff_support",
    }
    base.update(over)
    return base


def test_create_staff_admin_returns_201(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    create_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    new_user = _make_user(email="new@rehome.one", role="staff_support")
    create_mock.return_value = new_user
    token = make_jwt(roles=["staff_admin"], sub="admin-user-1")
    resp = client.post(
        "/api/v1/admin/users",
        json=_create_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "new@rehome.one"
    assert resp.headers["Location"] == f"/api/v1/admin/users/{new_user.id}"


def test_create_uses_jwt_sub_for_audit(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    create_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    new_user = _make_user()
    create_mock.return_value = new_user
    token = make_jwt(roles=["staff_admin"], sub="admin-uuid-here")
    resp = client.post(
        "/api/v1/admin/users",
        json=_create_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    audit_kwargs = override_repo["audit"].call_args.kwargs
    assert audit_kwargs["actor_sub"] == "admin-uuid-here"
    assert audit_kwargs["action"] == "admin.kb_user.created"


def test_create_duplicate_email_returns_409(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    create_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    create_mock.side_effect = IntegrityError("dup", None, BaseException("UQ"))
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/users",
        json=_create_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


def test_create_invalid_role_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/users",
        json=_create_body(role="god_mode"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_create_invalid_email_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/users",
        json=_create_body(email="not-an-email"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_create_extra_field_returns_422(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/users",
        json=_create_body(evil_field=1),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /admin/users/{id}


def test_get_user_not_found_returns_404(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    get_mock.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/users/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_get_user_returns_view(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    user = _make_user()
    get_mock.return_value = user
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/users/{user.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == user.email


# ---------------------------------------------------------------------------
# PATCH /admin/users/{id}


def test_patch_404_when_not_found(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    get_mock.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/users/{uuid4()}",
        json={"role": "staff_legal"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_patch_applies_role_change_and_audits(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    user = _make_user(role="staff_support")
    get_mock.return_value = user
    token = make_jwt(roles=["staff_admin"], sub="actor-1")
    resp = client.patch(
        f"/api/v1/admin/users/{user.id}",
        json={"role": "staff_legal", "permissions": ["export"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "staff_legal"
    assert body["permissions"] == ["export"]
    audit_kwargs = override_repo["audit"].call_args.kwargs
    assert audit_kwargs["action"] == "admin.kb_user.updated"
    assert set(audit_kwargs["metadata"]["updated_fields"]) == {"role", "permissions"}


def test_patch_empty_body_is_noop(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    update_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Empty PATCH body — no-op (нет UPDATE, нет audit row)."""
    user = _make_user()
    get_mock.return_value = user
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/users/{user.id}",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    update_mock.assert_not_awaited()
    override_repo["audit"].assert_not_awaited()


# ---------------------------------------------------------------------------
# DELETE /admin/users/{id}


def test_delete_404_when_not_found(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    get_mock.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/admin/users/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_delete_active_returns_204_and_audits(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    user = _make_user(status="ACTIVE")
    get_mock.return_value = user
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/admin/users/{user.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    audit_kwargs = override_repo["audit"].call_args.kwargs
    assert audit_kwargs["action"] == "admin.kb_user.deactivated"


def test_delete_already_archived_is_noop_no_audit(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    get_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Idempotent: повторный DELETE на ARCHIVED → 204 без audit."""
    user = _make_user(status="ARCHIVED")
    get_mock.return_value = user
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/admin/users/{user.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    override_repo["audit"].assert_not_awaited()


# ---------------------------------------------------------------------------
# Cursor invalid


def test_list_invalid_cursor_returns_400(
    client: TestClient,
    override_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/users?cursor=NOT-VALID-BASE64",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
