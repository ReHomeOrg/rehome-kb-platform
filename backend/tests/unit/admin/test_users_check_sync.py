"""Drift: KbUser model enums ↔ migration 0024 CHECK constraint values."""

from __future__ import annotations

import re
from pathlib import Path

from src.api.admin.users_models import KB_USER_ROLES, KB_USER_STATUSES

_MIGRATION = (
    Path(__file__).resolve().parents[3] / "alembic" / "versions" / "20260519_010000_kb_users.py"
)


def _extract_tuple(source: str, name: str) -> set[str]:
    pattern = re.compile(rf"{re.escape(name)}\s*=\s*\((.*?)\)", re.DOTALL)
    m = pattern.search(source)
    assert m is not None, f"Constant {name} не найдена в migration"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_migration_roles_match_model() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    migration_roles = _extract_tuple(src, "_ROLES")
    assert migration_roles == set(KB_USER_ROLES), (
        f"Drift: model KB_USER_ROLES vs migration _ROLES.\n"
        f"  model only: {set(KB_USER_ROLES) - migration_roles}\n"
        f"  migration only: {migration_roles - set(KB_USER_ROLES)}"
    )


def test_migration_statuses_match_model() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    migration_statuses = _extract_tuple(src, "_STATUSES")
    assert migration_statuses == set(KB_USER_STATUSES)
