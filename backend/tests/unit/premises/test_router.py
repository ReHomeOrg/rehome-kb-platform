"""Unit tests для premises router (#142)."""

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
    c.owner = {"name": "Owner", "phone": "+7"}
    c.owner_representative = None
    c.current_tenant = {"name": "Tenant"}
    c.financial_data = {"rent": 50000}
    c.tenant_info = {"wifi": "secret"}
    c.internal_data = {"notes": "vip"}
    c.extra_identification = {"floor": 5}
    c.created_at = datetime.now(UTC)
    c.updated_at = datetime.now(UTC)
    c.archived_at = None
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


@pytest.fixture
def get_by_slug_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def list_published_mock() -> AsyncMock:
    return AsyncMock(return_value=([], False))


@pytest.fixture
def override_repo(
    get_by_slug_mock: AsyncMock,
    list_published_mock: AsyncMock,
) -> Iterator[tuple[AsyncMock, AsyncMock]]:
    repo = PremisesRepository.__new__(PremisesRepository)
    repo.get_by_slug = get_by_slug_mock  # type: ignore[method-assign]
    repo.list_published = list_published_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_premises_repository] = lambda: repo
    yield get_by_slug_mock, list_published_mock
    app.dependency_overrides.pop(get_premises_repository, None)


# ---------------------------------------------------------------------------
# GET /premises-cards/{slug}


def test_get_invalid_slug_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    """Slug pattern reject'ит uppercase / spaces."""
    resp = client.get("/api/v1/premises-cards/Invalid Slug!")
    assert resp.status_code == 422


def test_get_not_found_returns_404(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/premises-cards/missing")
    assert resp.status_code == 404


def test_get_anon_returns_identification_only(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    """ADR-0003: anon scope получает identification, не ПДн."""
    get_mock, _ = override_repo
    get_mock.return_value = _make_card()
    resp = client.get("/api/v1/premises-cards/spb-test-001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["address"] == "Test address 1"
    assert body["postal_code"] == "190000"
    # ПДн / staff blocks omitted (None в Pydantic → JSON null).
    assert body.get("owner") is None
    assert body.get("financial_data") is None
    assert body.get("tenant_info") is None
    assert body.get("internal_data") is None
    assert body.get("internal_code") is None


def test_get_staff_returns_all_blocks(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    get_mock, _ = override_repo
    get_mock.return_value = _make_card()
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/premises-cards/spb-test-001",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["owner"] == {"name": "Owner", "phone": "+7"}
    assert body["current_tenant"] == {"name": "Tenant"}
    assert body["financial_data"] == {"rent": 50000}
    assert body["tenant_info"] == {"wifi": "secret"}
    assert body["internal_data"] == {"notes": "vip"}
    assert body["internal_code"] == "СПБ-Test-001"


def test_get_anon_dropped_for_draft(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    """ADR-0003: anon на DRAFT → 404 (Repository вернёт None из-за status filter)."""
    # get_by_slug возвращает None для anon scope at DRAFT — repository
    # отсекает на SQL уровне. Симулируем поведение: mock returns None.
    get_mock, _ = override_repo
    get_mock.return_value = None
    resp = client.get("/api/v1/premises-cards/draft-card")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /premises-cards (list)


def test_list_empty(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/premises-cards")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["pagination"] == {"cursor_next": None, "has_more": False}


def test_list_returns_summaries_no_pii(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """List response — только identification fields, даже для STAFF.

    PII никогда не возвращается в list endpoint'е (security-by-design;
    staff делает detail-запрос для каждой карточки если нужны PII).
    """
    _, list_mock = override_repo
    list_mock.return_value = ([_make_card(), _make_card(slug="another")], False)
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/premises-cards",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    # PremisesSummary НЕ имеет PII fields в schema → JSON их не содержит.
    for item in body["data"]:
        assert "owner" not in item
        assert "financial_data" not in item
        assert "tenant_info" not in item
        assert "internal_data" not in item


def test_list_has_more_emits_cursor(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    _, list_mock = override_repo
    list_mock.return_value = ([_make_card()], True)
    resp = client.get("/api/v1/premises-cards?limit=1")
    body = resp.json()
    assert body["pagination"]["has_more"] is True
    assert body["pagination"]["cursor_next"] is not None


def test_list_invalid_cursor_returns_400(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/premises-cards?cursor=!!!malformed!!!")
    assert resp.status_code == 400


def test_list_limit_out_of_range_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/premises-cards?limit=0")
    assert resp.status_code == 422
    resp = client.get("/api/v1/premises-cards?limit=101")
    assert resp.status_code == 422
