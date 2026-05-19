"""Unit tests для premises write endpoints (#148)."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from src.api.audit import AuditRepository, get_audit_repository
from src.api.main import app
from src.api.premises.models import PremisesCard
from src.api.premises.repository import PremisesRepository, get_premises_repository


def _make_card(**over: Any) -> PremisesCard:
    c = PremisesCard()
    c.id = uuid4()
    c.slug = "spb-test-001"
    c.internal_code = None
    c.status = "DRAFT"
    c.premises_uuid = None
    c.address = "Test address 1"
    c.postal_code = None
    c.cadastral_number = None
    c.owner = {}
    c.owner_representative = None
    c.current_tenant = None
    c.financial_data = {}
    c.tenant_info = {}
    c.internal_data = {}
    c.extra_identification = {}
    c.created_at = datetime.now(UTC)
    c.updated_at = datetime.now(UTC)
    c.archived_at = None
    for k, v in over.items():
        setattr(c, k, v)
    return c


@pytest.fixture
def create_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def update_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def archive_mock() -> AsyncMock:
    return AsyncMock(return_value=False)


@pytest.fixture
def audit_record_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def override_deps(
    create_mock: AsyncMock,
    update_mock: AsyncMock,
    archive_mock: AsyncMock,
    audit_record_mock: AsyncMock,
) -> Iterator[tuple[AsyncMock, AsyncMock, AsyncMock, AsyncMock]]:
    repo = PremisesRepository.__new__(PremisesRepository)
    repo.create = create_mock  # type: ignore[method-assign]
    repo.update = update_mock  # type: ignore[method-assign]
    repo.archive = archive_mock  # type: ignore[method-assign]
    audit = AuditRepository.__new__(AuditRepository)
    audit.record = audit_record_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_premises_repository] = lambda: repo
    app.dependency_overrides[get_audit_repository] = lambda: audit
    yield create_mock, update_mock, archive_mock, audit_record_mock
    app.dependency_overrides.pop(get_premises_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)


# ---------------------------------------------------------------------------
# POST /premises-cards


def _valid_create_payload() -> dict[str, Any]:
    return {
        "slug": "spb-test-001",
        "address": "г. Санкт-Петербург, ул. Тест, д. 1",
        "status": "DRAFT",
        "internal_code": "СПБ-Test-001",
        "owner": {"name": "Иванов И.И.", "phone": "+7 999 1234567"},
        "financial_data": {"rent_amount": 50000},
    }


def test_create_requires_auth(client: TestClient, override_deps: None) -> None:
    resp = client.post("/api/v1/premises-cards", json=_valid_create_payload())
    assert resp.status_code == 401


def test_create_requires_staff_scope(
    client: TestClient,
    override_deps: None,
    make_jwt: Callable[..., str],
) -> None:
    """Non-staff (tenant) → 403."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/premises-cards",
        json=_valid_create_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_create_201_with_staff(
    client: TestClient,
    override_deps: None,
    create_mock: AsyncMock,
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    card = _make_card()
    create_mock.return_value = card
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/premises-cards",
        json=_valid_create_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    create_mock.assert_awaited_once()
    audit_kwargs = audit_record_mock.call_args.kwargs
    assert audit_kwargs["action"] == "premises.created"
    assert audit_kwargs["resource_id"] == card.slug
    # Location header.
    assert resp.headers["Location"] == f"/api/v1/premises-cards/{card.slug}"
    # STAFF response — все blocks включены (см. project_for_scope).
    body = resp.json()
    assert body["address"] == "Test address 1"


def test_create_invalid_slug_returns_422(
    client: TestClient,
    override_deps: None,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    payload = _valid_create_payload() | {"slug": "Invalid Slug!"}
    resp = client.post(
        "/api/v1/premises-cards",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_create_extra_field_returns_422(
    client: TestClient,
    override_deps: None,
    make_jwt: Callable[..., str],
) -> None:
    """extra='forbid' — unknown field → 422."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    payload = _valid_create_payload() | {"evil_field": 1}
    resp = client.post(
        "/api/v1/premises-cards",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_create_duplicate_slug_returns_409(
    client: TestClient,
    override_deps: None,
    create_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    create_mock.side_effect = IntegrityError("dup", None, Exception())
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/premises-cards",
        json=_valid_create_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


def test_create_invalid_status_returns_422(
    client: TestClient,
    override_deps: None,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    payload = _valid_create_payload() | {"status": "UNKNOWN"}
    resp = client.post(
        "/api/v1/premises-cards",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /premises-cards/{slug}


def test_patch_requires_staff(
    client: TestClient,
    override_deps: None,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/premises-cards/spb-test-001",
        json={"status": "PUBLISHED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_patch_not_found_returns_404(
    client: TestClient,
    override_deps: None,
    update_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    update_mock.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/premises-cards/missing",
        json={"status": "PUBLISHED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_patch_applies_fields_and_audits(
    client: TestClient,
    override_deps: None,
    update_mock: AsyncMock,
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    update_mock.return_value = _make_card(status="PUBLISHED", address="New address")
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/premises-cards/spb-test-001",
        json={"status": "PUBLISHED", "address": "New address"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    # patch dict только non-None.
    patch_dict = update_mock.call_args.kwargs["patch"]
    assert patch_dict == {"status": "PUBLISHED", "address": "New address"}
    # Audit metadata содержит fields_changed.
    audit_kwargs = audit_record_mock.call_args.kwargs
    assert audit_kwargs["action"] == "premises.updated"
    assert set(audit_kwargs["metadata"]["fields_changed"]) == {"status", "address"}


# ---------------------------------------------------------------------------
# #221: premises_card.updated webhook event


@pytest.fixture
def premises_dispatch_mock() -> Iterator[AsyncMock]:
    """Override no-op dispatcher с tracking mock для assert'ов."""
    from unittest.mock import MagicMock

    from src.api.webhooks.dispatcher import (
        WebhookEventDispatcher,
        get_webhook_event_dispatcher,
    )

    dispatch = AsyncMock(return_value=1)
    fake = MagicMock(spec=WebhookEventDispatcher)
    fake.dispatch = dispatch
    app.dependency_overrides[get_webhook_event_dispatcher] = lambda: fake
    yield dispatch
    app.dependency_overrides.pop(get_webhook_event_dispatcher, None)


def test_patch_fires_premises_card_updated(
    client: TestClient,
    override_deps: None,
    update_mock: AsyncMock,
    premises_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """PATCH с changed fields → webhook event `premises_card.updated`."""
    card = _make_card(status="PUBLISHED", address="New address")
    update_mock.return_value = card
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/premises-cards/spb-test-001",
        json={"status": "PUBLISHED", "address": "New address"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    premises_dispatch_mock.assert_awaited_once()
    kwargs = premises_dispatch_mock.call_args.kwargs
    assert kwargs["event_type"] == "premises_card.updated"
    payload = kwargs["payload"]
    assert payload["premises_id"] == str(card.id)
    assert payload["slug"] == card.slug
    assert set(payload["changed_fields"]) == {"status", "address"}


def test_patch_empty_body_skips_premises_dispatch(
    client: TestClient,
    override_deps: None,
    update_mock: AsyncMock,
    premises_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Empty PATCH (all None) → no webhook (subscriber не ждёт bare touch)."""
    card = _make_card(status="PUBLISHED")
    update_mock.return_value = card
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/premises-cards/spb-test-001",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    premises_dispatch_mock.assert_not_awaited()


def test_patch_invalid_slug_returns_422(
    client: TestClient,
    override_deps: None,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/premises-cards/Invalid Slug",
        json={"status": "PUBLISHED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /premises-cards/{slug}


def test_delete_requires_staff(
    client: TestClient,
    override_deps: None,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.delete(
        "/api/v1/premises-cards/spb-test-001",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_delete_archives_and_audits(
    client: TestClient,
    override_deps: None,
    archive_mock: AsyncMock,
    audit_record_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    archive_mock.return_value = True
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        "/api/v1/premises-cards/spb-test-001",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    archive_mock.assert_awaited_once_with("spb-test-001")
    audit_kwargs = audit_record_mock.call_args.kwargs
    assert audit_kwargs["action"] == "premises.archived"


def test_delete_idempotent_already_archived(
    client: TestClient,
    override_deps: None,
    archive_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Already-ARCHIVED → archive() returns False → 404."""
    archive_mock.return_value = False
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        "/api/v1/premises-cards/missing-or-archived",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
