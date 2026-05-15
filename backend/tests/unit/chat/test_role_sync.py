"""Contract test: ChatRole three-way sync (#208).

Mirror BBB/CCC/DDD pattern. Источники истины:
1. `backend/src/api/chat/llm/base.py` — `LLMRole = Literal[...]`.
2. `frontend/lib/api/types.ts` — `export type ChatRole = ...`.
3. `alembic/versions/20260512_160000_chat_sessions_messages.py` —
   ck_chat_messages_role CHECK constraint.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from src.api.chat.llm.base import LLMRole

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TS_TYPES_PATH = _REPO_ROOT / "frontend" / "lib" / "api" / "types.ts"
_MIGRATION_PATH = (
    _REPO_ROOT / "backend" / "alembic" / "versions" / "20260512_160000_chat_sessions_messages.py"
)


def _parse_ts_chat_role() -> set[str]:
    src = _TS_TYPES_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"export\s+type\s+ChatRole\s*=\s*([^;]+);",
        src,
    )
    assert match is not None, "ChatRole type not found в types.ts"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _parse_migration_check() -> set[str]:
    src = _MIGRATION_PATH.read_text(encoding="utf-8")
    match = re.search(
        r'"role IN \(([^)]+)\)",\s*name="ck_chat_messages_role"',
        src,
    )
    assert match is not None, "ck_chat_messages_role CHECK не найден"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def _backend_literals() -> set[str]:
    return set(get_args(LLMRole))


def test_backend_and_frontend_chat_role_match() -> None:
    backend = _backend_literals()
    frontend = _parse_ts_chat_role()
    assert backend == frontend, (
        f"ChatRole drift backend ↔ frontend:\n"
        f"  backend only: {sorted(backend - frontend)}\n"
        f"  frontend only: {sorted(frontend - backend)}"
    )


def test_backend_and_migration_chat_role_match() -> None:
    backend = _backend_literals()
    migration = _parse_migration_check()
    assert backend == migration, (
        f"ChatRole drift backend ↔ CHECK constraint:\n"
        f"  backend only: {sorted(backend - migration)}\n"
        f"  migration only: {sorted(migration - backend)}"
    )
