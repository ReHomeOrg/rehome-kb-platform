"""Drift sync: backend access.py constants ↔ migration 0019 CHECK.

Если кто-то добавит/удалит тип / финансовую группу / статус в
`src/api/collaborators/access.py` без правки migration, или наоборот,
этот тест поймает несоответствие до production. ADR-0014 §1: drift
test — обязателен.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.api.collaborators.access import (
    COLLABORATOR_TYPES,
    FINANCIAL_GROUPS,
    LEGAL_ENTITY_TYPES,
    STATUSES,
    TYPE_TO_FINANCIAL_GROUP,
)

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "20260516_010000_collaborators_foundation.py"
)


def _extract_tuple(source: str, name: str) -> set[str]:
    """Извлечь `_TYPES = (...)` constants из migration."""
    pattern = re.compile(rf"{re.escape(name)}\s*=\s*\((.*?)\)", re.DOTALL)
    m = pattern.search(source)
    assert m is not None, f"Constant {name} не найдена в migration"
    body = m.group(1)
    return set(re.findall(r'"([^"]+)"', body))


def test_migration_types_match_access_constants() -> None:
    """COLLABORATOR_TYPES (access.py) == _TYPES (migration 0019)."""
    src = _MIGRATION.read_text(encoding="utf-8")
    migration_types = _extract_tuple(src, "_TYPES")
    assert migration_types == set(COLLABORATOR_TYPES), (
        f"Drift между access.py и migration:\n"
        f"  access only: {set(COLLABORATOR_TYPES) - migration_types}\n"
        f"  migration only: {migration_types - set(COLLABORATOR_TYPES)}"
    )


def test_migration_financial_groups_match_access() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    migration_groups = _extract_tuple(src, "_FINANCIAL_GROUPS")
    assert migration_groups == set(FINANCIAL_GROUPS)


def test_migration_statuses_match_access() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    migration_statuses = _extract_tuple(src, "_STATUSES")
    assert migration_statuses == set(STATUSES)


def test_migration_legal_entity_types_match_access() -> None:
    src = _MIGRATION.read_text(encoding="utf-8")
    migration_legal_entity = _extract_tuple(src, "_LEGAL_ENTITY_TYPES")
    assert migration_legal_entity == set(LEGAL_ENTITY_TYPES)


def test_migration_type_group_pairs_match_access() -> None:
    """Invariant pairs из migration соответствуют TYPE_TO_FINANCIAL_GROUP map.

    ТЗ §10.3 фиксирует mapping; код и schema БД должны иметь одинаковый view.
    """
    src = _MIGRATION.read_text(encoding="utf-8")
    pattern = re.compile(r"_TYPE_GROUP_PAIRS\s*=\s*\((.*?)\n\)", re.DOTALL)
    m = pattern.search(src)
    assert m is not None
    body = m.group(1)
    # Каждая пара формата ("type_name", "group_letter"),
    pair_pattern = re.compile(r'\("([^"]+)",\s*"([^"]+)"\)')
    migration_pairs = dict(pair_pattern.findall(body))
    assert migration_pairs == TYPE_TO_FINANCIAL_GROUP, (
        f"Drift type↔group invariant:\n"
        f"  access only: {set(TYPE_TO_FINANCIAL_GROUP.items()) - set(migration_pairs.items())}\n"
        f"  migration only: {set(migration_pairs.items()) - set(TYPE_TO_FINANCIAL_GROUP.items())}"
    )
