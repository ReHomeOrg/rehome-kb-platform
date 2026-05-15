"""Unit tests для HR pydantic schemas (#204).

Coverage: HrEmployeeInput / HrEmployeePatch — input validation
(max_length, status enum, extra=forbid). Boundary + reject cases —
regression guard на ослабление constraints.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from src.api.hr.schemas import HrEmployeeInput, HrEmployeePatch

# ---------------------------------------------------------------------------
# HrEmployeeInput


def test_minimal_valid_input() -> None:
    model = HrEmployeeInput(
        full_name="Иван Иванов",
        position="Менеджер",
        hire_date=date(2026, 1, 15),
    )
    assert model.status == "ACTIVE"  # default
    assert model.contact_info == {}
    assert model.notes == {}


def test_extra_field_rejected() -> None:
    """`extra='forbid'` — unknown fields → 422 (anti-typo, anti-injection)."""
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        HrEmployeeInput.model_validate(
            {
                "full_name": "X",
                "position": "P",
                "hire_date": "2026-01-01",
                "unknown_field": "y",
            }
        )


def test_full_name_too_long_rejected() -> None:
    with pytest.raises(ValidationError, match="at most 200"):
        HrEmployeeInput(
            full_name="x" * 201,
            position="P",
            hire_date=date(2026, 1, 1),
        )


def test_full_name_empty_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 1"):
        HrEmployeeInput(
            full_name="",
            position="P",
            hire_date=date(2026, 1, 1),
        )


def test_personnel_number_too_long_rejected() -> None:
    with pytest.raises(ValidationError, match="at most 32"):
        HrEmployeeInput(
            full_name="X",
            position="P",
            hire_date=date(2026, 1, 1),
            personnel_number="P" * 33,
        )


def test_status_invalid_value_rejected() -> None:
    """Только ACTIVE/ON_LEAVE/TERMINATED — anti-status-injection."""
    with pytest.raises(ValidationError, match="Input should be"):
        HrEmployeeInput.model_validate(
            {
                "full_name": "X",
                "position": "P",
                "hire_date": "2026-01-01",
                "status": "FIRED",
            }
        )


def test_status_terminated_accepted() -> None:
    model = HrEmployeeInput(
        full_name="X",
        position="P",
        hire_date=date(2026, 1, 1),
        status="TERMINATED",
        termination_date=date(2026, 5, 1),
    )
    assert model.status == "TERMINATED"


def test_position_max_length_boundary() -> None:
    """Position 200 chars exactly — boundary accepted."""
    model = HrEmployeeInput(
        full_name="X",
        position="P" * 200,
        hire_date=date(2026, 1, 1),
    )
    assert len(model.position) == 200


def test_contact_info_accepts_arbitrary_dict() -> None:
    """JSONB — schema-flexible. Form data passed through."""
    model = HrEmployeeInput(
        full_name="X",
        position="P",
        hire_date=date(2026, 1, 1),
        contact_info={"phone": "+79991234567", "email": "x@y.ru"},
    )
    assert model.contact_info["phone"] == "+79991234567"


# ---------------------------------------------------------------------------
# HrEmployeePatch


def test_patch_all_fields_optional() -> None:
    """Patch — все fields optional. Empty body — valid (no-op)."""
    model = HrEmployeePatch()
    assert model.full_name is None
    assert model.status is None


def test_patch_extra_field_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        HrEmployeePatch.model_validate({"unknown_field": "x"})


def test_patch_partial_update_full_name_only() -> None:
    model = HrEmployeePatch(full_name="New Name")
    assert model.full_name == "New Name"
    assert model.position is None  # not touched


def test_patch_full_name_constraints_apply() -> None:
    """Constraints applied и в patch."""
    with pytest.raises(ValidationError, match="at most 200"):
        HrEmployeePatch(full_name="X" * 201)
