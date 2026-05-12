"""Sync-test: Document.allowed_*() методы совпадают с CHECK constraints.

При расширении enum (например, новый category=G) разработчик обязан
обновить и Python-метод, и Alembic-миграцию. Этот тест ловит drift
между ними по тексту констрейнта.
"""

from sqlalchemy import CheckConstraint

from src.api.documents.models import Document


def _extract_in_values(constraint_sql: str) -> set[str]:
    """`category IN ('A', 'B', ...)` → `{'A', 'B', ...}`."""
    start = constraint_sql.find("(")
    end = constraint_sql.find(")")
    assert start != -1
    assert end != -1
    parts = constraint_sql[start + 1 : end].split(",")
    return {p.strip().strip("'") for p in parts}


def _get_check_constraint(name: str) -> str:
    for c in Document.__table_args__:
        if isinstance(c, CheckConstraint) and c.name == name:
            return str(c.sqltext)
    raise AssertionError(f"CheckConstraint {name} not found")


def test_category_check_matches_python_enum() -> None:
    sql = _get_check_constraint("ck_documents_category")
    values = _extract_in_values(sql)
    assert values == set(Document.allowed_categories())


def test_status_check_matches_python_enum() -> None:
    sql = _get_check_constraint("ck_documents_status")
    values = _extract_in_values(sql)
    assert values == set(Document.allowed_statuses())


def test_confidentiality_check_matches_python_enum() -> None:
    sql = _get_check_constraint("ck_documents_confidentiality")
    values = _extract_in_values(sql)
    assert values == set(Document.allowed_confidentialities())
