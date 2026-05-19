"""Unit tests для GET /premises-cards/{premises_id}/financial (#226, ТЗ §3.5)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.premises.models import PremisesCard
from src.api.premises.repository import PremisesRepository, get_premises_repository


def _make_card(**overrides: Any) -> PremisesCard:
    c = PremisesCard()
    c.id = uuid4()
    c.slug = "spb-test-001"
    c.internal_code = "СПБ-Test-001"
    c.status = "PUBLISHED"
    c.premises_uuid = uuid4()
    c.address = "Test address 1"
    c.postal_code = "190000"
    c.cadastral_number = "78:14:0000000:0001"
    c.owner = {"name": "Owner"}
    c.owner_representative = None
    c.current_tenant = None
    c.financial_data = {}
    c.tenant_info = {}
    c.internal_data = {}
    c.extra_identification = {}
    c.created_at = datetime.now(UTC)
    c.updated_at = datetime.now(UTC)
    c.archived_at = None
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


@pytest.fixture
def get_by_id_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def override_repo(get_by_id_mock: AsyncMock) -> Iterator[AsyncMock]:
    repo = PremisesRepository.__new__(PremisesRepository)
    repo.get_by_id = get_by_id_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_premises_repository] = lambda: repo
    yield get_by_id_mock
    app.dependency_overrides.pop(get_premises_repository, None)


# ---------------------------------------------------------------------------
# Auth gating


def test_anon_returns_401(client: TestClient, override_repo: AsyncMock) -> None:
    """Без JWT → 401 (require_authenticated)."""
    resp = client.get(f"/api/v1/premises-cards/{uuid4()}/financial")
    assert resp.status_code == 401
    override_repo.assert_not_awaited()


def test_tenant_returns_403(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Tenant scope → 403 (только landlord/staff per ТЗ §3.5)."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/premises-cards/{uuid4()}/financial",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    override_repo.assert_not_awaited()


def test_guest_returns_403(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Authenticated guest (no role) → 403."""
    token = make_jwt(roles=[], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/premises-cards/{uuid4()}/financial",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_agent_returns_403(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Agent видит AGENT-level статьи, но НЕ financial block (ТЗ §3.5)."""
    token = make_jwt(roles=["agent"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/premises-cards/{uuid4()}/financial",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_landlord_with_no_card_returns_404(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Landlord, но id не существует → 404."""
    override_repo.return_value = None
    token = make_jwt(roles=["landlord"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/premises-cards/{uuid4()}/financial",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_staff_with_no_card_returns_404(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    override_repo.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/premises-cards/{uuid4()}/financial",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Happy path — landlord


def test_landlord_with_card_returns_financial_block(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Landlord → financial_data возвращается как FinancialBlock projection."""
    card = _make_card(
        financial_data={
            "contract_url": "https://docs.rehome.one/contracts/abc.pdf",
            "contract_start": "2026-01-01",
            "contract_end": "2027-01-01",
            "monthly_rent": 50000,
            "rent_due_day": 15,
            "service_fee": {
                "amount": 10000,
                "paid_at": "2026-01-01T10:00:00Z",
                "status": "PAID",
                "fiscal_receipt_url": "https://r.example/1.pdf",
            },
            "payment_history": [
                {
                    "date": "2026-02-15",
                    "amount": 50000,
                    "type": "rent",
                    "status": "RECEIVED",
                }
            ],
            "current_debt": 0,
            "utilities_included": True,
            "platform_commission_percent": 7.0,
            "insurance_policy": None,
        }
    )
    override_repo.return_value = card
    token = make_jwt(roles=["landlord"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/premises-cards/{card.id}/financial",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["monthly_rent"] == 50000
    assert body["rent_due_day"] == 15
    assert body["service_fee"]["status"] == "PAID"
    assert body["service_fee"]["amount"] == 10000
    assert body["payment_history"][0]["type"] == "rent"
    assert body["platform_commission_percent"] == 7.0
    assert body["utilities_included"] is True


def test_empty_financial_data_returns_default_block(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Карточка без `financial_data` (пустой JSONB) → 200 с default-полями.

    Forward-compat: премисес без контракта — нормальный кейс.
    """
    card = _make_card(financial_data={})
    override_repo.return_value = card
    token = make_jwt(roles=["landlord"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/premises-cards/{card.id}/financial",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # current_debt default 0; остальные null/empty.
    assert body["current_debt"] == 0
    assert body["payment_history"] == []
    assert body["monthly_rent"] is None
    assert body["service_fee"] is None


def test_staff_can_view_financial(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """staff_admin → видит financial так же, как landlord."""
    card = _make_card(financial_data={"monthly_rent": 75000})
    override_repo.return_value = card
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/premises-cards/{card.id}/financial",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["monthly_rent"] == 75000


def test_invalid_uuid_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["landlord"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/premises-cards/not-a-uuid/financial",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_extra_jsonb_fields_ignored(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """JSONB может содержать unknown keys — extra='ignore' их выкидывает."""
    card = _make_card(
        financial_data={
            "monthly_rent": 50000,
            "legacy_deposit_field": 100000,  # not в FinancialBlock schema
            "internal_notes": "skip me",
        }
    )
    override_repo.return_value = card
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/premises-cards/{card.id}/financial",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "legacy_deposit_field" not in body
    assert "internal_notes" not in body
    assert body["monthly_rent"] == 50000
