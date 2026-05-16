"""Unit tests для collaborators/access.py — ADR-0014 §3 invariants."""

from __future__ import annotations

import pytest

from src.api.auth.scope import AccessLevel
from src.api.collaborators.access import (
    COLLABORATOR_TYPES,
    FINANCIAL_GROUPS,
    STATUSES,
    TYPE_TO_FINANCIAL_GROUP,
    compute_visible_groups,
    derive_financial_group,
)

# ---------------------------------------------------------------------------
# Enum invariants (drift guard)


def test_14_collaborator_types_per_tz() -> None:
    """ТЗ §10.2 фиксирует ровно 14 типов."""
    assert len(COLLABORATOR_TYPES) == 14


def test_4_financial_groups_per_tz() -> None:
    """ТЗ §10.3 фиксирует ровно 4 группы (A, B, C, D)."""
    assert set(FINANCIAL_GROUPS) == {"A", "B", "C", "D"}


def test_5_statuses_per_tz() -> None:
    """ТЗ §10.5 фиксирует 5 статусов lifecycle."""
    assert set(STATUSES) == {"DRAFT", "PENDING_REVIEW", "ACTIVE", "SUSPENDED", "ARCHIVED"}


def test_type_to_group_covers_13_of_14_types() -> None:
    """'other' не в map'е — это wildcard (любая группа). Остальные 13 имеют
    закреплённую группу."""
    assert len(TYPE_TO_FINANCIAL_GROUP) == 13
    assert "other" not in TYPE_TO_FINANCIAL_GROUP
    assert set(TYPE_TO_FINANCIAL_GROUP.keys()) == set(COLLABORATOR_TYPES) - {"other"}


def test_type_to_group_values_are_valid_groups() -> None:
    """Каждое value в map'е — известная финансовая группа."""
    assert set(TYPE_TO_FINANCIAL_GROUP.values()) <= set(FINANCIAL_GROUPS)


# ---------------------------------------------------------------------------
# derive_financial_group


def test_derive_payment_partner_returns_a() -> None:
    assert derive_financial_group("payment_partner") == "A"


def test_derive_management_company_returns_d() -> None:
    assert derive_financial_group("management_company") == "D"


def test_derive_insurance_returns_c() -> None:
    assert derive_financial_group("insurance") == "C"


def test_derive_cleaning_returns_b() -> None:
    assert derive_financial_group("cleaning") == "B"


def test_derive_other_raises() -> None:
    """`other` требует явно указать группу (ТЗ §10.3)."""
    with pytest.raises(ValueError, match="other"):
        derive_financial_group("other")


def test_derive_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="Unknown collaborator type"):
        derive_financial_group("not_a_real_type")


# ---------------------------------------------------------------------------
# compute_visible_groups


def test_guest_sees_only_group_d() -> None:
    """Гость (только PUBLIC) видит только публичные контакты — D-группа."""
    levels = frozenset({AccessLevel.PUBLIC})
    assert compute_visible_groups(levels) == frozenset({"D"})


def test_logged_user_still_only_group_d() -> None:
    """LOGGED не расширяет видимость коллаборантов (ADR-0014 §3)."""
    levels = frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED})
    assert compute_visible_groups(levels) == frozenset({"D"})


def test_agent_still_only_group_d() -> None:
    levels = frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.AGENT})
    assert compute_visible_groups(levels) == frozenset({"D"})


def test_staff_sees_all_groups() -> None:
    levels = frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.STAFF})
    assert compute_visible_groups(levels) == frozenset({"A", "B", "C", "D"})


def test_legal_sees_all_groups() -> None:
    levels = frozenset({AccessLevel.PUBLIC, AccessLevel.LEGAL})
    assert compute_visible_groups(levels) == frozenset({"A", "B", "C", "D"})


def test_hr_restricted_sees_all_groups() -> None:
    """HR не интересуется коллаборантами, но если scope даёт — full visibility."""
    levels = frozenset({AccessLevel.PUBLIC, AccessLevel.HR_RESTRICTED})
    assert compute_visible_groups(levels) == frozenset({"A", "B", "C", "D"})


def test_empty_access_levels_defensive_default_group_d() -> None:
    """Пустой frozenset → защитный default {'D'} (теоретически невозможный case)."""
    assert compute_visible_groups(frozenset()) == frozenset({"D"})
