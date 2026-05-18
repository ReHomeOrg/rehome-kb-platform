"""Drift sync: model enums ↔ migration 0024 CHECK constraints."""

from __future__ import annotations

import re
from pathlib import Path

from src.api.admin.security_incidents_models import (
    DETECTED_BY,
    SEVERITIES,
    STATUSES,
)

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "20260520_010000_security_incidents.py"
)


def _extract_tuple(source: str, name: str) -> set[str]:
    pattern = re.compile(rf"{re.escape(name)}\s*=\s*\((.*?)\)", re.DOTALL)
    m = pattern.search(source)
    assert m is not None, f"Constant {name} не найдена в migration"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_severities_match() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    assert _extract_tuple(src, "_SEVERITIES") == set(SEVERITIES)


def test_statuses_match() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    assert _extract_tuple(src, "_STATUSES") == set(STATUSES)


def test_detected_by_match() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    assert _extract_tuple(src, "_DETECTED_BY") == set(DETECTED_BY)


def test_requires_rkn_helper() -> None:
    """РКН gate per ФЗ-152 §17.1."""
    from src.api.admin.security_incidents_models import requires_rkn_notification

    assert requires_rkn_notification("low") is False
    assert requires_rkn_notification("medium") is False
    assert requires_rkn_notification("high") is True
    assert requires_rkn_notification("critical") is True
