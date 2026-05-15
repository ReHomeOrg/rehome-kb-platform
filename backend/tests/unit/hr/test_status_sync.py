"""Contract test: EmployeeStatus трёхсторонний sync (#205).

Источники истины — три места:
1. `backend/src/api/hr/schemas.py` — `EmployeeStatus = Literal[...]`.
2. `frontend/lib/api/types.ts` — `export type EmployeeStatus = ...`.
3. `alembic/versions/20260514_030000_hr_foundation.py` — CHECK constraint
   `ck_hr_employees_status`.

Если значения разойдутся:
- Frontend send'нёт status backend rejected (или наоборот).
- DB примет status, который application reject'нёт.
- Migration accept'нёт row, который Pydantic reject'нёт на read.

Тест парсит все три и сравнивает sets. Drift → CI fail.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from src.api.hr.schemas import EmployeeStatus

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TS_TYPES_PATH = _REPO_ROOT / "frontend" / "lib" / "api" / "types.ts"
_MIGRATION_PATH = (
    _REPO_ROOT / "backend" / "alembic" / "versions" / "20260514_030000_hr_foundation.py"
)


def _parse_ts_enum() -> set[str]:
    """Extract values из `export type EmployeeStatus = "A" | "B" | "C";`."""
    src = _TS_TYPES_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"export\s+type\s+EmployeeStatus\s*=\s*([^;]+);",
        src,
    )
    assert match is not None, "EmployeeStatus type not found в types.ts"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _parse_migration_check() -> set[str]:
    """Extract из `"status IN ('A', 'B', 'C')", name="ck_hr_employees_status"`."""
    src = _MIGRATION_PATH.read_text(encoding="utf-8")
    match = re.search(
        r'"status IN \(([^)]+)\)",\s*name="ck_hr_employees_status"',
        src,
    )
    assert match is not None, "ck_hr_employees_status CHECK не найден"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def _backend_literals() -> set[str]:
    return set(get_args(EmployeeStatus))


def test_backend_and_frontend_employee_status_match() -> None:
    backend = _backend_literals()
    frontend = _parse_ts_enum()
    assert backend == frontend, (
        f"EmployeeStatus drift backend ↔ frontend:\n"
        f"  backend only: {sorted(backend - frontend)}\n"
        f"  frontend only: {sorted(frontend - backend)}"
    )


def test_backend_and_migration_employee_status_match() -> None:
    backend = _backend_literals()
    migration = _parse_migration_check()
    assert backend == migration, (
        f"EmployeeStatus drift backend ↔ CHECK constraint:\n"
        f"  backend only: {sorted(backend - migration)}\n"
        f"  migration only: {sorted(migration - backend)}"
    )


def test_frontend_and_migration_employee_status_match() -> None:
    """Транзитивно покрывает frontend ↔ migration (избыточно но fails fast)."""
    frontend = _parse_ts_enum()
    migration = _parse_migration_check()
    assert frontend == migration
