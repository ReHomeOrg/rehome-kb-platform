"""Unit-тесты для compute_allowed_confidentialities (E2.8 #56).

Маппинг scope → confidentiality критичен для ADR-0003 — ошибка тут
может допустить guest'а к RESTRICTED документам.
"""

import pytest

from src.api.auth.scope import AccessLevel
from src.api.documents.access import compute_allowed_confidentialities


@pytest.mark.security
def test_public_scope_sees_only_public_confidentiality() -> None:
    """ADR-0003: guest (PUBLIC scope) → только PUBLIC documents."""
    result = compute_allowed_confidentialities(frozenset({AccessLevel.PUBLIC}))
    assert result == frozenset({"PUBLIC"})


@pytest.mark.security
def test_logged_scope_sees_public_and_internal() -> None:
    result = compute_allowed_confidentialities(frozenset({AccessLevel.LOGGED}))
    assert result == frozenset({"PUBLIC", "INTERNAL"})


@pytest.mark.security
def test_staff_scope_sees_all_three() -> None:
    result = compute_allowed_confidentialities(frozenset({AccessLevel.STAFF}))
    assert result == frozenset({"PUBLIC", "INTERNAL", "RESTRICTED"})


@pytest.mark.security
def test_agent_scope_sees_public_and_internal_not_restricted() -> None:
    """Regression защита: AGENT не должен видеть RESTRICTED документы."""
    result = compute_allowed_confidentialities(frozenset({AccessLevel.AGENT}))
    assert "RESTRICTED" not in result
    assert result == frozenset({"PUBLIC", "INTERNAL"})


@pytest.mark.security
def test_empty_access_levels_defaults_to_public() -> None:
    """Защитный дефолт: пустой scope → PUBLIC (не падаем в IN ())."""
    result = compute_allowed_confidentialities(frozenset())
    assert result == frozenset({"PUBLIC"})


def test_combined_scope_unions_confidentialities() -> None:
    """LOGGED + STAFF → объединение (все 3)."""
    result = compute_allowed_confidentialities(frozenset({AccessLevel.LOGGED, AccessLevel.STAFF}))
    assert result == frozenset({"PUBLIC", "INTERNAL", "RESTRICTED"})


def test_legal_and_hr_restricted_see_restricted() -> None:
    legal = compute_allowed_confidentialities(frozenset({AccessLevel.LEGAL}))
    hr = compute_allowed_confidentialities(frozenset({AccessLevel.HR_RESTRICTED}))
    assert "RESTRICTED" in legal
    assert "RESTRICTED" in hr
