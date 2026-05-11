"""Тесты для Scope, AccessLevel, compute_scope, compute_access_levels."""

import pytest

from src.api.auth.scope import (
    SCOPE_TO_ACCESS_LEVELS,
    AccessLevel,
    Scope,
    compute_access_levels,
    compute_scope,
)


def test_no_roles_returns_guest() -> None:
    assert compute_scope([]) == Scope.GUEST
    assert compute_access_levels([]) == frozenset({AccessLevel.PUBLIC})


def test_compute_scope_uses_priority_not_first_role() -> None:
    # Если у пользователя 'agent' и 'staff_admin' — приоритет staff_admin.
    assert compute_scope(["agent", "staff_admin"]) == Scope.STAFF_ADMIN
    assert compute_scope(["staff_admin", "agent"]) == Scope.STAFF_ADMIN
    # Tenant + landlord — порядок не roles[0].
    assert compute_scope(["tenant", "landlord"]) == Scope.LANDLORD
    assert compute_scope(["landlord", "tenant"]) == Scope.LANDLORD


def test_compute_scope_unknown_roles_ignored() -> None:
    assert compute_scope(["unknown_role"]) == Scope.GUEST
    assert compute_scope(["tenant", "unknown_role"]) == Scope.TENANT


def test_compute_access_levels_single_role() -> None:
    assert compute_access_levels(["tenant"]) == frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED})
    assert compute_access_levels(["agent"]) == frozenset(
        {AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.AGENT}
    )


def test_compute_access_levels_multi_role_union() -> None:
    """Union AccessLevel-ов для multi-role — намеренное поведение (ADR-0007)."""
    levels = compute_access_levels(["staff_admin", "staff_hr"])
    # Должны быть все 6 уровней (admin + hr = full coverage).
    assert AccessLevel.PUBLIC in levels
    assert AccessLevel.LOGGED in levels
    assert AccessLevel.AGENT in levels
    assert AccessLevel.STAFF in levels
    assert AccessLevel.LEGAL in levels
    assert AccessLevel.HR_RESTRICTED in levels  # от staff_hr


def test_compute_access_levels_unknown_role_ignored() -> None:
    assert compute_access_levels(["unknown_role"]) == frozenset({AccessLevel.PUBLIC})
    # Корректные роли работают рядом с неизвестными.
    assert compute_access_levels(["agent", "unknown"]) == frozenset(
        {AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.AGENT}
    )


def test_staff_admin_does_not_have_hr_restricted_access_level() -> None:
    """КРИТИЧЕСКИЙ ИНВАРИАНТ ADR-0003: staff_admin НЕ имеет HR_RESTRICTED.

    Этот тест защищает от регрессии при будущих изменениях
    SCOPE_TO_ACCESS_LEVELS. Если этот тест падает — нарушен ADR-0003
    и требуется новый ADR.
    """
    admin_levels = SCOPE_TO_ACCESS_LEVELS[Scope.STAFF_ADMIN]
    assert AccessLevel.HR_RESTRICTED not in admin_levels
    # Прямая проверка с реальным input.
    assert AccessLevel.HR_RESTRICTED not in compute_access_levels(["staff_admin"])


def test_staff_hr_has_hr_restricted_but_not_legal() -> None:
    """ADR-0003: staff_hr изолирован от LEGAL/AGENT."""
    hr_levels = SCOPE_TO_ACCESS_LEVELS[Scope.STAFF_HR]
    assert AccessLevel.HR_RESTRICTED in hr_levels
    assert AccessLevel.LEGAL not in hr_levels
    assert AccessLevel.AGENT not in hr_levels


def test_guest_has_only_public() -> None:
    assert SCOPE_TO_ACCESS_LEVELS[Scope.GUEST] == frozenset({AccessLevel.PUBLIC})


@pytest.mark.parametrize(
    ("roles", "expected_scope"),
    [
        (["staff_admin"], Scope.STAFF_ADMIN),
        (["staff_hr"], Scope.STAFF_HR),
        (["staff_legal"], Scope.STAFF_LEGAL),
        (["staff_support"], Scope.STAFF_SUPPORT),
        (["agent"], Scope.AGENT),
        (["landlord"], Scope.LANDLORD),
        (["tenant"], Scope.TENANT),
        (["guest"], Scope.GUEST),
    ],
)
def test_compute_scope_single_role(roles: list[str], expected_scope: Scope) -> None:
    assert compute_scope(roles) == expected_scope
