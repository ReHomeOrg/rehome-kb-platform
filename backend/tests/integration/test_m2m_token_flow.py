"""Integration: m2m Client Credentials Grant + claims contract."""

import pytest

from tests.integration.conftest import KC_REALM, KC_URL, decode_jwt_payload


@pytest.mark.integration
def test_m2m_token_has_required_claims(m2m_token: str) -> None:
    """JWT содержит обязательные claims из ADR-0007 + ПЗ API 2.3."""
    payload = decode_jwt_payload(m2m_token)
    assert payload["iss"] == f"{KC_URL}/realms/{KC_REALM}"
    assert payload["sub"], "sub must be non-empty"
    assert payload["typ"] == "Bearer"
    assert "exp" in payload
    assert "iat" in payload


@pytest.mark.integration
def test_m2m_token_aud_equals_client_id(m2m_token: str) -> None:
    """`aud` claim равен `rehome-platform-m2m` благодаря audience mapper.

    Mapper зафиксирован в `infra/keycloak/realm-export.json`, добавлен в
    Issue #21 (E1.3.4). Без mapper'а Keycloak не выставляет aud для m2m,
    и backend `KC_VERIFY_AUD=true` отвергал бы валидные токены.
    """
    payload = decode_jwt_payload(m2m_token)
    aud = payload.get("aud")
    # Keycloak может выставить aud как строку (одиночная) или массив строк.
    if isinstance(aud, list):
        assert "rehome-platform-m2m" in aud
    else:
        assert aud == "rehome-platform-m2m"


@pytest.mark.integration
def test_m2m_token_contains_staff_admin_role(m2m_token: str) -> None:
    """Service-account-пользователь имеет realm-role `staff_admin` (см. realm-export.json)."""
    payload = decode_jwt_payload(m2m_token)
    roles = payload["realm_access"]["roles"]
    assert "staff_admin" in roles
