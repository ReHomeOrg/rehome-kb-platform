"""Contract test: DocumentFileFormat three-way sync (#209).

FileFormat дублирован в backend в двух местах (schemas.py + router.py)
— исторически (TODO: refactor — router should import). Тест держит
их синхронными до тех пор, пока deduplicate не land'нет.

Источники истины:
1. `backend/src/api/documents/schemas.py` — `FileFormat = Literal[...]`.
2. `backend/src/api/documents/router.py` — copy того же Literal (path param).
3. `frontend/lib/api/types.ts` — `export type DocumentFileFormat = ...`.

NB: backend DB не enforce'ит — формат хранится в JSONB `files`. Тест
ловит drift на application layer только.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from src.api.documents.router import FileFormat as RouterFileFormat
from src.api.documents.schemas import FileFormat as SchemasFileFormat

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TS_TYPES_PATH = _REPO_ROOT / "frontend" / "lib" / "api" / "types.ts"


def _parse_ts_type() -> set[str]:
    src = _TS_TYPES_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"export\s+type\s+DocumentFileFormat\s*=\s*([^;]+);",
        src,
    )
    assert match is not None, "DocumentFileFormat type not found в types.ts"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_schemas_and_router_file_format_match() -> None:
    """Внутренний backend duplication — оба места synced до refactor'а."""
    schemas = set(get_args(SchemasFileFormat))
    router = set(get_args(RouterFileFormat))
    assert schemas == router, (
        f"FileFormat drift внутри backend:\n"
        f"  in schemas only: {sorted(schemas - router)}\n"
        f"  in router only:  {sorted(router - schemas)}"
    )


def test_backend_and_frontend_file_format_match() -> None:
    backend = set(get_args(SchemasFileFormat))
    frontend = _parse_ts_type()
    assert backend == frontend, (
        f"DocumentFileFormat drift backend ↔ frontend:\n"
        f"  backend only: {sorted(backend - frontend)}\n"
        f"  frontend only: {sorted(frontend - backend)}"
    )
