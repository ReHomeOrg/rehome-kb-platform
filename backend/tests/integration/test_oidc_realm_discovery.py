"""Integration: OIDC discovery endpoint Keycloak realm."""

import httpx
import pytest

from tests.integration.conftest import KC_REALM, KC_URL


@pytest.mark.integration
def test_discovery_endpoint_responds() -> None:
    """`.well-known/openid-configuration` отвечает 200 с корректным issuer."""
    response = httpx.get(
        f"{KC_URL}/realms/{KC_REALM}/.well-known/openid-configuration",
        timeout=10.0,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["issuer"] == f"{KC_URL}/realms/{KC_REALM}"
    assert data["jwks_uri"] == f"{KC_URL}/realms/{KC_REALM}/protocol/openid-connect/certs"
    assert "RS256" in data["id_token_signing_alg_values_supported"]


@pytest.mark.integration
def test_jwks_endpoint_returns_keys() -> None:
    """JWKS endpoint отдаёт RS256 ключ для signature verification."""
    response = httpx.get(
        f"{KC_URL}/realms/{KC_REALM}/protocol/openid-connect/certs",
        timeout=10.0,
    )
    assert response.status_code == 200
    data = response.json()
    keys = data["keys"]
    assert len(keys) >= 1
    rs256_keys = [k for k in keys if k.get("alg") == "RS256"]
    assert rs256_keys, "RS256 key not found in JWKS"
    rs256_key = rs256_keys[0]
    assert rs256_key["kty"] == "RSA"
    assert "n" in rs256_key  # RSA modulus
    assert "e" in rs256_key  # RSA exponent
