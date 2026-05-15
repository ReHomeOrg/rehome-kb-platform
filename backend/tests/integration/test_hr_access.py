"""Integration: HR endpoints — access boundary с реальным Keycloak.

Этот файл проверяет ТОЛЬКО ADR-0003 security boundary через HTTP.
Positive path (staff_hr → 200) — backlog #29: требует второго m2m
client с `staff_hr` role в realm. Сейчас прод m2m client имеет
`staff_admin`, который НАМЕРЕННО не имеет HR_RESTRICTED (ФЗ-152
strict separation).

Покрывает все 5 endpoint'ов: list, get, create, patch, delete.
Регрессионный guard: попытка убрать `require_access_level(HR_RESTRICTED)`
сломает эти тесты.
"""

from uuid import uuid4

import httpx
import pytest

# ---------------------------------------------------------------------------
# Anonymous → 401


@pytest.mark.integration
def test_hr_list_anon_401(kb_client: httpx.Client) -> None:
    response = kb_client.get("/api/v1/hr/employees")
    assert response.status_code == 401


@pytest.mark.integration
def test_hr_get_anon_401(kb_client: httpx.Client) -> None:
    response = kb_client.get(f"/api/v1/hr/employees/{uuid4()}")
    assert response.status_code == 401


@pytest.mark.integration
def test_hr_create_anon_401(kb_client: httpx.Client) -> None:
    response = kb_client.post(
        "/api/v1/hr/employees",
        json={
            "full_name": "Test",
            "position": "Engineer",
            "hire_date": "2026-01-01",
        },
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# m2m (staff_admin) → 403 — strict separation (ADR-0003, ФЗ-152)


@pytest.mark.integration
def test_hr_list_m2m_staff_admin_403(kb_client: httpx.Client, m2m_token: str) -> None:
    """staff_admin НЕ имеет HR_RESTRICTED — 403 не 401."""
    response = kb_client.get(
        "/api/v1/hr/employees",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 403


@pytest.mark.integration
def test_hr_get_m2m_staff_admin_403(kb_client: httpx.Client, m2m_token: str) -> None:
    response = kb_client.get(
        f"/api/v1/hr/employees/{uuid4()}",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 403


@pytest.mark.integration
def test_hr_create_m2m_staff_admin_403(kb_client: httpx.Client, m2m_token: str) -> None:
    response = kb_client.post(
        "/api/v1/hr/employees",
        json={
            "full_name": "Test",
            "position": "Engineer",
            "hire_date": "2026-01-01",
        },
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 403


@pytest.mark.integration
def test_hr_patch_m2m_staff_admin_403(kb_client: httpx.Client, m2m_token: str) -> None:
    response = kb_client.patch(
        f"/api/v1/hr/employees/{uuid4()}",
        json={"position": "Senior Engineer"},
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 403


@pytest.mark.integration
def test_hr_delete_m2m_staff_admin_403(kb_client: httpx.Client, m2m_token: str) -> None:
    response = kb_client.delete(
        f"/api/v1/hr/employees/{uuid4()}",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 403
