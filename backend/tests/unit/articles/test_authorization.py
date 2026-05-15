"""Unit tests для ensure_can_write_access_level (#212).

ADR-0003 Level-2 invariant: writer не может create/modify статью
с access_level, который сам не видит на read. Regression guard
на ослабление write-side check'а.
"""

import pytest

from src.api.articles.authorization import ensure_can_write_access_level
from src.api.auth.exceptions import ForbiddenError
from src.api.auth.scope import AccessLevel


def test_passes_when_target_in_levels() -> None:
    """STAFF user writing STAFF article — OK."""
    ensure_can_write_access_level(
        AccessLevel.STAFF,
        frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.STAFF}),
    )


def test_rejects_when_target_not_in_levels() -> None:
    """staff_admin (без HR_RESTRICTED) → HR_RESTRICTED article → 403."""
    with pytest.raises(ForbiddenError, match="access_level you don't have"):
        ensure_can_write_access_level(
            AccessLevel.HR_RESTRICTED,
            frozenset(
                {
                    AccessLevel.PUBLIC,
                    AccessLevel.LOGGED,
                    AccessLevel.AGENT,
                    AccessLevel.STAFF,
                    AccessLevel.LEGAL,
                }
            ),
        )


def test_rejects_legal_writer_without_legal() -> None:
    """staff_support (STAFF без LEGAL) → LEGAL article → 403."""
    with pytest.raises(ForbiddenError):
        ensure_can_write_access_level(
            AccessLevel.LEGAL,
            frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.STAFF}),
        )


def test_passes_public_writer_for_public() -> None:
    """Guest/anonymous flow — PUBLIC writer для PUBLIC article."""
    ensure_can_write_access_level(
        AccessLevel.PUBLIC,
        frozenset({AccessLevel.PUBLIC}),
    )


def test_rejects_empty_levels() -> None:
    """Defensive: empty levels (auth bug?) → 403 для любого target."""
    with pytest.raises(ForbiddenError):
        ensure_can_write_access_level(AccessLevel.PUBLIC, frozenset())


def test_hr_writer_with_hr_passes() -> None:
    """staff_hr → HR_RESTRICTED article — OK."""
    ensure_can_write_access_level(
        AccessLevel.HR_RESTRICTED,
        frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.HR_RESTRICTED}),
    )
