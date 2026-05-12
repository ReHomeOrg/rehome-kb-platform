"""Sync-тесты: значения Article.allowed_*() ≡ CHECK constraints в миграции.

`allowed_*()` методы дублируют список enum-значений (audience/status/
access_level) в коде приложения. Если их обновить, не обновив CHECK
constraint в миграции — production-БД будет принимать значение, которое
приложение отвергнет (или наоборот). Этот тест парсит migration-файл и
сверяет литералы.

Источник истины — OpenAPI schema (см. docs/handoff/01_postanovka/04_openapi.yaml).
Оба места ниже обязаны быть с ним согласованы.
"""

import re
from pathlib import Path

import pytest

from src.api.articles.models import Article

MIGRATION_FILE = (
    Path(__file__).parents[3] / "alembic" / "versions" / "20260512_014421_initial_articles.py"
)


def _extract_check_values(check_name: str) -> set[str]:
    """Достаёт literal-значения из CHECK constraint миграции по имени."""
    content = MIGRATION_FILE.read_text(encoding="utf-8")
    # Ищем строку `name="<check_name>"` и берём предшествующий ей `... IN (...)`.
    pattern = rf'"([^"]+ IN \([^)]+\))",\s*name="{check_name}"'
    match = re.search(pattern, content)
    if match is None:
        raise AssertionError(f"CHECK '{check_name}' не найден в миграции")
    in_clause = match.group(1)
    # Достаём все 'literal' значения.
    values = re.findall(r"'([^']+)'", in_clause)
    return set(values)


@pytest.mark.parametrize(
    ("check_name", "method_name"),
    [
        ("ck_articles_audience", "allowed_audiences"),
        ("ck_articles_status", "allowed_statuses"),
        ("ck_articles_access_level", "allowed_access_levels"),
    ],
)
def test_allowed_values_match_migration_check(check_name: str, method_name: str) -> None:
    migration_values = _extract_check_values(check_name)
    app_values = set(getattr(Article, method_name)())
    assert migration_values == app_values, (
        f"Drift between migration CHECK '{check_name}' и "
        f"Article.{method_name}(): migration={migration_values}, "
        f"app={app_values}. Обновите ОБА места согласованно "
        "(OpenAPI — источник истины)."
    )
