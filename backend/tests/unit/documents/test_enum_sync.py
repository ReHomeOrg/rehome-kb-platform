"""Contract test: Documents enums three-way sync (#207).

Mirror BBB/CCC pattern. 3 enums × 3 sources = 9 pairwise checks
(приведены к 6 — без транзитивных дублей):

1. `backend/src/api/documents/schemas.py` — Category/Status/Confidentiality Literals.
2. `frontend/lib/api/types.ts` — DocumentCategory/Status/Confidentiality types.
3. `alembic/versions/20260512_150000_documents_table.py` — ck_documents_*
   CHECK constraints.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from src.api.documents.schemas import Category, Confidentiality, Status

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TS_TYPES_PATH = _REPO_ROOT / "frontend" / "lib" / "api" / "types.ts"
_MIGRATION_PATH = (
    _REPO_ROOT / "backend" / "alembic" / "versions" / "20260512_150000_documents_table.py"
)


def _parse_ts_type(name: str) -> set[str]:
    """Extract literal values из `export type Foo = "A" | "B";`."""
    src = _TS_TYPES_PATH.read_text(encoding="utf-8")
    match = re.search(
        rf"export\s+type\s+{re.escape(name)}\s*=\s*([^;]+);",
        src,
    )
    assert match is not None, f"{name} type not found в types.ts"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _parse_migration_check(field: str, check_name: str) -> set[str]:
    src = _MIGRATION_PATH.read_text(encoding="utf-8")
    match = re.search(
        rf'"{field} IN \(([^)]+)\)",\s*name="{check_name}"',
        src,
    )
    assert match is not None, f"{check_name} CHECK не найден"
    return set(re.findall(r"'([^']+)'", match.group(1)))


# ---------------------------------------------------------------------------
# Category


def test_category_backend_frontend_match() -> None:
    backend = set(get_args(Category))
    frontend = _parse_ts_type("DocumentCategory")
    assert backend == frontend


def test_category_backend_migration_match() -> None:
    backend = set(get_args(Category))
    migration = _parse_migration_check("category", "ck_documents_category")
    assert backend == migration


# ---------------------------------------------------------------------------
# Status


def test_status_backend_frontend_match() -> None:
    backend = set(get_args(Status))
    frontend = _parse_ts_type("DocumentStatus")
    assert backend == frontend


def test_status_backend_migration_match() -> None:
    backend = set(get_args(Status))
    migration = _parse_migration_check("status", "ck_documents_status")
    assert backend == migration


# ---------------------------------------------------------------------------
# Confidentiality


def test_confidentiality_backend_frontend_match() -> None:
    backend = set(get_args(Confidentiality))
    frontend = _parse_ts_type("DocumentConfidentiality")
    assert backend == frontend


def test_confidentiality_backend_migration_match() -> None:
    backend = set(get_args(Confidentiality))
    migration = _parse_migration_check("confidentiality", "ck_documents_confidentiality")
    assert backend == migration
