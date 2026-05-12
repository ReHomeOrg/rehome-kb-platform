"""Sync-test: ChatMessage.allowed_roles() ≡ CHECK constraint."""

from sqlalchemy import CheckConstraint

from src.api.chat.models import ChatMessage


def _extract_in_values(constraint_sql: str) -> set[str]:
    start = constraint_sql.find("(")
    end = constraint_sql.find(")")
    assert start != -1
    assert end != -1
    parts = constraint_sql[start + 1 : end].split(",")
    return {p.strip().strip("'") for p in parts}


def test_role_check_matches_python_enum() -> None:
    constraint: CheckConstraint | None = None
    for c in ChatMessage.__table_args__:
        if isinstance(c, CheckConstraint) and c.name == "ck_chat_messages_role":
            constraint = c
            break
    assert constraint is not None
    values = _extract_in_values(str(constraint.sqltext))
    assert values == set(ChatMessage.allowed_roles())
