"""Contract test: frontend WEBHOOK_EVENTS ↔ backend WebhookEvent (Issue #98).

Frontend `frontend/lib/api/types.ts` хардкодит const tuple `WEBHOOK_EVENTS`
с допустимыми event'ами. Backend `WebhookEvent` StrEnum — источник истины.
Этот тест парсит TS-файл регуляркой и сравнивает множества — drift
немедленно ломает Backend CI job.

NB: Парсинг через regex, а не JS-AST, потому что backend job не таскает
Node.js — добавлять зависимость ради одного теста несоразмерно.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.api.webhooks.events import ALLOWED_EVENTS

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TS_TYPES_PATH = _REPO_ROOT / "frontend" / "lib" / "api" / "types.ts"


def _parse_ts_events() -> set[str]:
    """Extract event strings from `WEBHOOK_EVENTS = [...] as const;` literal."""
    src = _TS_TYPES_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"export\s+const\s+WEBHOOK_EVENTS\s*=\s*\[(.*?)\]\s*as\s+const\s*;",
        src,
        flags=re.DOTALL,
    )
    assert match is not None, "WEBHOOK_EVENTS literal not found in types.ts"
    # Extract quoted strings inside the array; tolerate either quote style
    # (Prettier may flip codebases between single/double quotes).
    parsed = set(re.findall(r"""["']([^"']+)["']""", match.group(1)))
    assert parsed, "Failed to parse any event strings — TS quoting changed?"
    return parsed


def test_frontend_webhook_events_match_backend_enum() -> None:
    """Drift между TS const и Python enum → CI fail."""
    frontend = _parse_ts_events()
    backend = ALLOWED_EVENTS
    assert frontend == backend, (
        f"WEBHOOK_EVENTS drift detected.\n"
        f"  in frontend only: {sorted(frontend - backend)}\n"
        f"  in backend only:  {sorted(backend - frontend)}"
    )
