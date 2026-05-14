"""Unit tests для vault group member endpoints (#155)."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit import AuditRepository, get_audit_repository
from src.api.main import app
from src.api.vault.models import VaultGroup, VaultGroupMember
from src.api.vault.repository import VaultRepository, get_vault_repository


def _make_group() -> VaultGroup:
    g = VaultGroup()
    g.id = uuid4()
    g.name = "Team"
    g.description = None
    g.created_by = uuid4()
    g.created_at = datetime.now(UTC)
    return g


def _make_member(
    group_id: Any,
    user_id: Any,
    role: str = "member",
) -> VaultGroupMember:
    m = VaultGroupMember()
    m.group_id = group_id
    m.user_id = user_id
    m.role = role
    m.added_at = datetime.now(UTC)
    return m


@pytest.fixture
def repo_mocks() -> dict[str, AsyncMock]:
    return {
        "get_group": AsyncMock(return_value=None),
        "get_group_member": AsyncMock(return_value=None),
        "is_group_member": AsyncMock(return_value=False),
        "list_group_members": AsyncMock(return_value=[]),
        "add_group_member": AsyncMock(),
        "remove_group_member": AsyncMock(return_value=False),
    }


@pytest.fixture
def audit_record_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def override_deps(
    repo_mocks: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
) -> Iterator[dict[str, AsyncMock]]:
    repo = VaultRepository.__new__(VaultRepository)
    for name, mock in repo_mocks.items():
        setattr(repo, name, mock)
    audit = AuditRepository.__new__(AuditRepository)
    audit.record = audit_record_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_vault_repository] = lambda: repo
    app.dependency_overrides[get_audit_repository] = lambda: audit
    yield repo_mocks
    app.dependency_overrides.pop(get_vault_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)


# ---------------------------------------------------------------------------
# GET /groups/{id}/members


def test_list_members_requires_auth(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
) -> None:
    resp = client.get(f"/api/v1/vault/groups/{uuid4()}/members")
    assert resp.status_code == 401


def test_list_members_404_when_non_member(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Non-member видит 404, не distinguish'ит exists/not-exists."""
    override_deps["is_group_member"].return_value = False
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/vault/groups/{uuid4()}/members",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_list_members_returns_data_for_member(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    gid = uuid4()
    override_deps["is_group_member"].return_value = True
    override_deps["list_group_members"].return_value = [
        _make_member(gid, uuid4(), "owner"),
        _make_member(gid, uuid4(), "member"),
    ]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/vault/groups/{gid}/members",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert {m["role"] for m in body["data"]} == {"owner", "member"}


# ---------------------------------------------------------------------------
# POST /groups/{id}/members


def test_add_member_requires_auth(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
) -> None:
    resp = client.post(
        f"/api/v1/vault/groups/{uuid4()}/members",
        json={"user_id": str(uuid4())},
    )
    assert resp.status_code == 401


def test_add_member_404_when_group_missing(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    override_deps["get_group"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/vault/groups/{uuid4()}/members",
        json={"user_id": str(uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_add_member_404_when_caller_not_member(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Не-member выглядит как 404 (anti-enumeration)."""
    override_deps["get_group"].return_value = _make_group()
    override_deps["get_group_member"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/vault/groups/{uuid4()}/members",
        json={"user_id": str(uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_add_member_403_when_caller_not_owner(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Member but not owner → 403."""
    gid = uuid4()
    actor = uuid4()
    override_deps["get_group"].return_value = _make_group()
    override_deps["get_group_member"].return_value = _make_member(gid, actor, "member")
    token = make_jwt(roles=["staff_admin"], sub=str(actor))
    resp = client.post(
        f"/api/v1/vault/groups/{gid}/members",
        json={"user_id": str(uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_add_member_409_if_already_member(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    gid = uuid4()
    actor = uuid4()
    override_deps["get_group"].return_value = _make_group()
    override_deps["get_group_member"].return_value = _make_member(gid, actor, "owner")
    override_deps["is_group_member"].return_value = True  # target already member
    token = make_jwt(roles=["staff_admin"], sub=str(actor))
    resp = client.post(
        f"/api/v1/vault/groups/{gid}/members",
        json={"user_id": str(uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


def test_add_member_success(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    gid = uuid4()
    actor = uuid4()
    new_member = uuid4()
    override_deps["get_group"].return_value = _make_group()
    override_deps["get_group_member"].return_value = _make_member(gid, actor, "owner")
    override_deps["is_group_member"].return_value = False
    override_deps["add_group_member"].return_value = _make_member(gid, new_member)
    token = make_jwt(roles=["staff_admin"], sub=str(actor))
    resp = client.post(
        f"/api/v1/vault/groups/{gid}/members",
        json={"user_id": str(new_member)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == str(new_member)
    assert audit_record_mock.call_args.kwargs["action"] == "vault.group.member.added"


def test_add_member_invalid_role(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Pydantic pattern validates role."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/vault/groups/{uuid4()}/members",
        json={"user_id": str(uuid4()), "role": "admin"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /groups/{id}/members/{user_id}


def test_remove_member_requires_auth(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
) -> None:
    resp = client.delete(f"/api/v1/vault/groups/{uuid4()}/members/{uuid4()}")
    assert resp.status_code == 401


def test_remove_member_403_when_caller_not_owner(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    gid = uuid4()
    actor = uuid4()
    override_deps["get_group"].return_value = _make_group()
    override_deps["get_group_member"].return_value = _make_member(gid, actor, "member")
    token = make_jwt(roles=["staff_admin"], sub=str(actor))
    resp = client.delete(
        f"/api/v1/vault/groups/{gid}/members/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_remove_member_cannot_remove_self(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """Owner can't remove себя — avoid orphan-management group."""
    gid = uuid4()
    actor = uuid4()
    override_deps["get_group"].return_value = _make_group()
    override_deps["get_group_member"].return_value = _make_member(gid, actor, "owner")
    token = make_jwt(roles=["staff_admin"], sub=str(actor))
    resp = client.delete(
        f"/api/v1/vault/groups/{gid}/members/{actor}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_remove_member_404_if_not_exists(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    gid = uuid4()
    actor = uuid4()
    override_deps["get_group"].return_value = _make_group()
    override_deps["get_group_member"].return_value = _make_member(gid, actor, "owner")
    override_deps["remove_group_member"].return_value = False
    token = make_jwt(roles=["staff_admin"], sub=str(actor))
    resp = client.delete(
        f"/api/v1/vault/groups/{gid}/members/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_remove_member_success(
    client: TestClient,
    override_deps: dict[str, AsyncMock],
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    gid = uuid4()
    actor = uuid4()
    target = uuid4()
    override_deps["get_group"].return_value = _make_group()
    override_deps["get_group_member"].return_value = _make_member(gid, actor, "owner")
    override_deps["remove_group_member"].return_value = True
    token = make_jwt(roles=["staff_admin"], sub=str(actor))
    resp = client.delete(
        f"/api/v1/vault/groups/{gid}/members/{target}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    assert audit_record_mock.call_args.kwargs["action"] == "vault.group.member.removed"
