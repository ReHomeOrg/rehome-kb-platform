"""Drift sync: AdminTask enums ↔ migration 0024_admin_tasks CHECK constraints."""

from __future__ import annotations

import re
from pathlib import Path

from src.api.admin.tasks_models import TASK_STATUSES, TASK_TYPES

_MIGRATION = (
    Path(__file__).resolve().parents[3] / "alembic" / "versions" / "20260523_020000_admin_tasks.py"
)


def _extract_tuple(source: str, name: str) -> set[str]:
    pattern = re.compile(rf"{re.escape(name)}\s*=\s*\((.*?)\)", re.DOTALL)
    m = pattern.search(source)
    assert m is not None, f"Constant {name} не найдена в migration"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_types_match() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    assert _extract_tuple(src, "_TYPES") == set(TASK_TYPES)


def test_statuses_match() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    assert _extract_tuple(src, "_STATUSES") == set(TASK_STATUSES)
