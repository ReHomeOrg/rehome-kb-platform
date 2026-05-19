"""Drift sync: model enums ↔ migration 0024 CHECK constraints (#232)."""

from __future__ import annotations

import re
from pathlib import Path

from src.api.admin.pd_requests_models import (
    PD_REQUEST_STATUSES,
    PD_REQUEST_TYPES,
)

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "20260521_010000_personal_data_requests.py"
)


def _extract_tuple(source: str, name: str) -> set[str]:
    pattern = re.compile(rf"{re.escape(name)}\s*=\s*\((.*?)\)", re.DOTALL)
    m = pattern.search(source)
    assert m is not None, f"Constant {name} не найдена"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_types_match() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    assert _extract_tuple(src, "_TYPES") == set(PD_REQUEST_TYPES)


def test_statuses_match() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    assert _extract_tuple(src, "_STATUSES") == set(PD_REQUEST_STATUSES)
