"""Contract test: audit-filters resource_type options ↔ backend RESOURCE_*
constants (#210).

Frontend `/admin/audit` UI содержит <select name="resource_type"> с
жёстко прописанными значениями. Backend генерит resource_type через
`RESOURCE_*` Final-constants в `audit/actions.py`. Если backend
добавит/удалит resource_type, frontend select может либо show'нуть
неактуальную опцию, либо missed новую.

Регулярка извлекает значения из обоих источников; разница =
fail с понятным diff.

NB: фронтенд select содержит plain опцию "" для «все» — её исключаем
из сравнения (sentinel, не resource).
"""

from __future__ import annotations

import re
from pathlib import Path

import src.api.audit.actions as audit_actions

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TS_FILTERS_PATH = (
    _REPO_ROOT / "frontend" / "app" / "admin" / "audit" / "_components" / "audit-filters.tsx"
)


def _backend_resources() -> set[str]:
    """Все RESOURCE_* constants из audit/actions.py."""
    return {
        value
        for name, value in vars(audit_actions).items()
        if name.startswith("RESOURCE_") and isinstance(value, str)
    }


def _parse_ts_options() -> set[str]:
    """Extract <option value="X"> из audit-filters.tsx (resource_type select)."""
    src = _TS_FILTERS_PATH.read_text(encoding="utf-8")
    # Берём строку c <option value="..."> в пределах <select name="resource_type">.
    select_match = re.search(
        r'<select\s+name="resource_type"[^>]*>(.*?)</select>',
        src,
        flags=re.DOTALL,
    )
    assert select_match is not None, '<select name="resource_type"> не найден'
    options = re.findall(r'<option value="([^"]*)"', select_match.group(1))
    # Sentinel «все» = пустая строка — исключаем.
    return {v for v in options if v}


def test_audit_filter_resource_options_match_backend_constants() -> None:
    backend = _backend_resources()
    frontend = _parse_ts_options()
    assert backend == frontend, (
        f"resource_type drift между backend RESOURCE_* и audit-filters.tsx:\n"
        f"  backend only (frontend missed): {sorted(backend - frontend)}\n"
        f"  frontend only (backend renamed?): {sorted(frontend - backend)}"
    )
