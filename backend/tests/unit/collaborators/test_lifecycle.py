"""Unit tests для lifecycle validators (ADR-0014 §5)."""

from __future__ import annotations

from src.api.collaborators.lifecycle import (
    LifecycleViolation,
    validate_activation,
    validate_suspension,
)

# ---------------------------------------------------------------------------
# validate_activation — happy paths


def test_activate_d_group_minimal_data_passes() -> None:
    """D-группа (management_company, emergency_service) — нет требований
    к контракту, counterparty_check, responsible_internal."""
    violations = validate_activation(
        current_status="DRAFT",
        financial_group="D",
        counterparty_check={},
        contract_document_id=None,
        responsible_internal=None,
    )
    assert violations == []


def test_activate_a_group_with_clean_check_and_contract_passes() -> None:
    """A-группа со всеми invariants — активируется."""
    violations = validate_activation(
        current_status="DRAFT",
        financial_group="A",
        counterparty_check={"result": "CLEAN", "checked_at": "2026-05-15T00:00:00Z"},
        contract_document_id="01234567-89ab-cdef-0123-456789abcdef",
        responsible_internal="staff-admin-1",
    )
    assert violations == []


def test_activate_from_suspended_status_allowed() -> None:
    """Re-activation: SUSPENDED → ACTIVE по тому же endpoint'у."""
    violations = validate_activation(
        current_status="SUSPENDED",
        financial_group="D",
        counterparty_check={},
        contract_document_id=None,
        responsible_internal=None,
    )
    assert violations == []


# ---------------------------------------------------------------------------
# validate_activation — invariant violations


def test_activate_from_active_returns_violation() -> None:
    """Уже ACTIVE — нельзя активировать повторно."""
    violations = validate_activation(
        current_status="ACTIVE",
        financial_group="D",
        counterparty_check={},
        contract_document_id=None,
        responsible_internal=None,
    )
    assert len(violations) == 1
    assert violations[0].field == "status"


def test_activate_from_archived_returns_violation() -> None:
    violations = validate_activation(
        current_status="ARCHIVED",
        financial_group="D",
        counterparty_check={},
        contract_document_id=None,
        responsible_internal=None,
    )
    assert any(v.field == "status" for v in violations)


def test_activate_a_group_without_clean_check_returns_violation() -> None:
    violations = validate_activation(
        current_status="DRAFT",
        financial_group="A",
        counterparty_check={"result": "YELLOW"},
        contract_document_id="x",
        responsible_internal="staff",
    )
    assert any(v.field == "counterparty_check.result" for v in violations)


def test_activate_a_group_without_contract_returns_violation() -> None:
    violations = validate_activation(
        current_status="DRAFT",
        financial_group="A",
        counterparty_check={"result": "CLEAN"},
        contract_document_id=None,
        responsible_internal="staff",
    )
    assert any(v.field == "contract_document_id" for v in violations)


def test_activate_b_group_without_contract_returns_violation() -> None:
    """B (через нас + комиссия) тоже требует договор."""
    violations = validate_activation(
        current_status="PENDING_REVIEW",
        financial_group="B",
        counterparty_check={"result": "CLEAN"},
        contract_document_id=None,
        responsible_internal="staff",
    )
    assert any(v.field == "contract_document_id" for v in violations)


def test_activate_c_group_requires_responsible_internal() -> None:
    violations = validate_activation(
        current_status="DRAFT",
        financial_group="C",
        counterparty_check={"result": "CLEAN"},
        contract_document_id="x",
        responsible_internal=None,
    )
    assert any(v.field == "responsible_internal" for v in violations)


def test_activate_d_group_does_not_require_contract_or_check() -> None:
    """D-группа — публичные/городские, без коммерческих отношений."""
    violations = validate_activation(
        current_status="DRAFT",
        financial_group="D",
        counterparty_check={"result": "RED"},  # игнорируется для D
        contract_document_id=None,
        responsible_internal=None,
    )
    assert violations == []


def test_activate_collects_all_violations_at_once() -> None:
    """Все violations возвращаются одним батчем (быстрее UX)."""
    violations = validate_activation(
        current_status="ACTIVE",  # not allowed
        financial_group="A",
        counterparty_check={},  # not CLEAN
        contract_document_id=None,
        responsible_internal=None,
    )
    fields = {v.field for v in violations}
    assert "status" in fields
    assert "counterparty_check.result" in fields
    assert "contract_document_id" in fields
    assert "responsible_internal" in fields


# ---------------------------------------------------------------------------
# validate_suspension


def test_suspend_from_active_passes() -> None:
    assert validate_suspension("ACTIVE") == []


def test_suspend_from_draft_returns_violation() -> None:
    violations = validate_suspension("DRAFT")
    assert len(violations) == 1
    assert violations[0].field == "status"


def test_suspend_from_suspended_idempotent_blocked() -> None:
    """SUSPENDED → SUSPENDED заблокирован — caller знает что delta была."""
    assert validate_suspension("SUSPENDED") != []


def test_suspend_from_archived_returns_violation() -> None:
    assert validate_suspension("ARCHIVED") != []


# ---------------------------------------------------------------------------
# LifecycleViolation namedtuple


def test_violation_as_dict_serializable() -> None:
    v = LifecycleViolation(field="x", reason="y")
    assert v.as_dict() == {"field": "x", "reason": "y"}
