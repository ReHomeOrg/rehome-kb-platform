"""Тесты dependency: token extraction, smuggling protection, scope/access_level."""

import logging
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient


def test_whoami_no_token_returns_guest(client: TestClient) -> None:
    response = client.get("/api/v1/whoami")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "guest"
    assert body["sub"] == ""
    assert body["username"] == ""
    assert body["roles"] == []
    assert body["access_levels"] == ["PUBLIC"]


def test_whoami_with_bearer_token(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["staff_support"], username="alice")
    response = client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "staff_support"
    assert body["sub"] == "test-user-uuid"
    assert body["username"] == "alice"
    assert body["roles"] == ["staff_support"]
    assert set(body["access_levels"]) == {"PUBLIC", "LOGGED", "STAFF"}


def test_whoami_with_cookie(client: TestClient, make_jwt: Callable[..., str]) -> None:
    """Browser flow: cookie kb_session."""
    token = make_jwt(roles=["tenant"], username="bob")
    client.cookies.set("kb_session", token)
    response = client.get("/api/v1/whoami")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "tenant"
    assert body["username"] == "bob"


def test_whoami_invalid_token_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/whoami", headers={"Authorization": "Bearer not.a.valid.jwt"})
    assert response.status_code == 401


def test_token_smuggling_authorization_wins(
    client: TestClient,
    make_jwt: Callable[..., str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Smuggling: оба источника → Authorization побеждает, warning логируется."""
    auth_token = make_jwt(roles=["staff_admin"], sub="auth-source-user")
    cookie_token = make_jwt(roles=["tenant"], sub="cookie-source-user")
    caplog.set_level(logging.WARNING, logger="src.api.auth.dependency")
    client.cookies.set("kb_session", cookie_token)
    response = client.get(
        "/api/v1/whoami",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    # Должен быть Authorization-источник (staff_admin), не cookie (tenant).
    assert body["scope"] == "staff_admin"
    assert body["sub"] == "auth-source-user"
    # Security-warning логируется.
    assert any("auth.token_source_conflict" in r.getMessage() for r in caplog.records)


def test_scope_not_accepted_from_query(
    client: TestClient,
) -> None:
    """Security: попытка передать scope=staff_admin в query — игнорируется."""
    response = client.get("/api/v1/whoami?scope=staff_admin")
    assert response.status_code == 200
    body = response.json()
    # Без токена — guest, query-параметр scope игнорируется.
    assert body["scope"] == "guest"
    assert body["roles"] == []


def test_scope_not_accepted_from_header(
    client: TestClient,
) -> None:
    """Security: X-Scope / X-Roles header игнорируются."""
    response = client.get(
        "/api/v1/whoami",
        headers={"X-Scope": "staff_admin", "X-Roles": "staff_admin"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "guest"
    assert body["roles"] == []


def test_multi_role_user_gets_union_access_levels(
    client: TestClient, make_jwt: Callable[..., str]
) -> None:
    """Multi-role: staff_admin + staff_hr → union = все 6 уровней (включая HR_RESTRICTED)."""
    token = make_jwt(roles=["staff_admin", "staff_hr"])
    response = client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    # scope display — берётся первый по приоритету (staff_admin).
    assert body["scope"] == "staff_admin"
    # access_levels — union, включает HR_RESTRICTED от staff_hr.
    assert "HR_RESTRICTED" in body["access_levels"]
    assert "LEGAL" in body["access_levels"]


def test_bearer_without_prefix_treated_as_no_token(client: TestClient) -> None:
    """Authorization без 'Bearer ' префикса — игнорируется."""
    response = client.get("/api/v1/whoami", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert response.status_code == 200
    assert response.json()["scope"] == "guest"


def test_empty_bearer_token_treated_as_no_token(client: TestClient) -> None:
    response = client.get("/api/v1/whoami", headers={"Authorization": "Bearer "})
    assert response.status_code == 200
    assert response.json()["scope"] == "guest"


def test_realm_access_roles_not_a_list_returns_empty(
    client: TestClient, make_jwt: Callable[..., str]
) -> None:
    """Защита от malformed JWT: realm_access.roles не list → []."""
    # extra_claims перезаписывает default `realm_access`.
    token = make_jwt(extra_claims={"realm_access": {"roles": "not-a-list"}})
    response = client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["roles"] == []
    assert response.json()["scope"] == "guest"
