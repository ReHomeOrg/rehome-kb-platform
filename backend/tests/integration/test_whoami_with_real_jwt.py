"""Integration: end-to-end /api/v1/whoami с реальным JWT от Keycloak.

Backend uvicorn должен быть запущен на KB_API_URL до прогона теста (CI делает
это через background uvicorn start).
"""

import httpx
import pytest


@pytest.mark.integration
def test_whoami_no_token_returns_guest(kb_client: httpx.Client) -> None:
    """Без токена scope=guest (E1.3.2 behavior, end-to-end через uvicorn)."""
    response = kb_client.get("/api/v1/whoami")
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "guest"
    assert body["roles"] == []
    assert body["access_levels"] == ["PUBLIC"]


@pytest.mark.integration
def test_whoami_with_real_m2m_token_returns_staff_admin(
    kb_client: httpx.Client, m2m_token: str
) -> None:
    """Реальный JWT от Keycloak: backend валидирует через JWKS → scope=staff_admin."""
    response = kb_client.get(
        "/api/v1/whoami",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "staff_admin"
    assert "staff_admin" in body["roles"]
    # ADR-0003: staff_admin имеет PUBLIC, LOGGED, AGENT, STAFF, LEGAL — НЕ HR_RESTRICTED.
    levels = set(body["access_levels"])
    assert {"PUBLIC", "LOGGED", "AGENT", "STAFF", "LEGAL"}.issubset(levels)
    assert "HR_RESTRICTED" not in levels


@pytest.mark.integration
def test_whoami_with_invalid_token_returns_401(kb_client: httpx.Client) -> None:
    """Невалидный JWT → 401 (backend верифицирует через JWKS, не доверяет на слово)."""
    response = kb_client.get(
        "/api/v1/whoami",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert response.status_code == 401
