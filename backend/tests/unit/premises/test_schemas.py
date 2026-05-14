"""Unit tests для PremisesCard schemas (#142)."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.api.auth.scope import AccessLevel
from src.api.premises.models import PremisesCard
from src.api.premises.schemas import project_for_scope


def _make_card(**overrides: Any) -> PremisesCard:
    c = PremisesCard()
    c.id = uuid4()
    c.slug = "test-prem"
    c.internal_code = "СПБ-Test-001"
    c.status = "PUBLISHED"
    c.premises_uuid = uuid4()
    c.address = "Test address 1"
    c.postal_code = "190000"
    c.cadastral_number = "78:14:0000000:0001"
    c.owner = {"name": "Иванов И.И.", "phone": "+7 999 1234567"}
    c.owner_representative = None
    c.current_tenant = {"name": "Петров П.П."}
    c.financial_data = {"rent_amount": 50000}
    c.tenant_info = {"wifi_password": "secret"}
    c.internal_data = {"manager_notes": "VIP клиент"}
    c.extra_identification = {"floor": 5, "area_sqm": 42}
    c.created_at = datetime.now(UTC)
    c.updated_at = datetime.now(UTC)
    c.archived_at = None
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def test_anon_sees_only_identification() -> None:
    """PUBLIC access_level (anon / tenant / landlord) → no PII blocks."""
    card = _make_card()
    view = project_for_scope(card, frozenset({AccessLevel.PUBLIC}))
    # Identification visible.
    assert view.address == "Test address 1"
    assert view.postal_code == "190000"
    assert view.cadastral_number == "78:14:0000000:0001"
    assert view.extra_identification == {"floor": 5, "area_sqm": 42}
    # ПДн blocks omitted.
    assert view.owner is None
    assert view.owner_representative is None
    assert view.current_tenant is None
    # Financial / tenant_info / internal_data omitted.
    assert view.financial_data is None
    assert view.tenant_info is None
    assert view.internal_data is None
    # Internal_code (staff-readable identifier) omitted.
    assert view.internal_code is None
    assert view.premises_uuid is None


def test_tenant_scope_sees_only_identification_in_stage1() -> None:
    """Stage 1: tenant видит identification только (как и anon).

    Stage 2 после Users + Contracts добавит per-tenant access к
    tenant_info — здесь регрессионный guard на текущее поведение.
    """
    view = project_for_scope(
        _make_card(),
        frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED}),
    )
    assert view.tenant_info is None
    assert view.financial_data is None
    assert view.owner is None


def test_staff_sees_all_blocks() -> None:
    """STAFF scope → все blocks включены."""
    card = _make_card()
    view = project_for_scope(
        card,
        frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.STAFF}),
    )
    assert view.owner == {"name": "Иванов И.И.", "phone": "+7 999 1234567"}
    assert view.current_tenant == {"name": "Петров П.П."}
    assert view.financial_data == {"rent_amount": 50000}
    assert view.tenant_info == {"wifi_password": "secret"}
    assert view.internal_data == {"manager_notes": "VIP клиент"}
    assert view.internal_code == "СПБ-Test-001"
    assert view.premises_uuid is not None


def test_legal_scope_sees_all_blocks() -> None:
    """LEGAL уровень — staff-tier, тоже видит PII."""
    view = project_for_scope(
        _make_card(),
        frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.LEGAL}),
    )
    assert view.owner is not None
    assert view.financial_data is not None


def test_hr_restricted_scope_sees_all_blocks() -> None:
    """HR_RESTRICTED уровень — также staff-tier."""
    view = project_for_scope(
        _make_card(),
        frozenset({AccessLevel.PUBLIC, AccessLevel.HR_RESTRICTED}),
    )
    assert view.owner is not None


def test_agent_scope_does_not_see_pii() -> None:
    """AGENT — НЕ staff. PII blocks остаются скрытыми."""
    view = project_for_scope(
        _make_card(),
        frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.AGENT}),
    )
    assert view.owner is None
    assert view.financial_data is None
