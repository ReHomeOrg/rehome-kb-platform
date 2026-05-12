"""Sync-test: ChatMessage/ChatEscalation enum methods ≡ CHECK constraints."""

from sqlalchemy import CheckConstraint
from sqlalchemy.orm import DeclarativeBase

from src.api.chat.models import ChatEscalation, ChatMessage


def _extract_in_values(constraint_sql: str) -> set[str]:
    start = constraint_sql.find("(")
    end = constraint_sql.find(")")
    assert start != -1
    assert end != -1
    parts = constraint_sql[start + 1 : end].split(",")
    return {p.strip().strip("'") for p in parts}


def _get_check_constraint(model: type[DeclarativeBase], name: str) -> CheckConstraint:
    for c in model.__table_args__:
        if isinstance(c, CheckConstraint) and c.name == name:
            return c
    raise AssertionError(f"CheckConstraint {name} not found on {model.__name__}")


def test_role_check_matches_python_enum() -> None:
    constraint = _get_check_constraint(ChatMessage, "ck_chat_messages_role")
    values = _extract_in_values(str(constraint.sqltext))
    assert values == set(ChatMessage.allowed_roles())


def test_escalation_priority_check_matches_python_enum() -> None:
    constraint = _get_check_constraint(ChatEscalation, "ck_chat_escalations_priority")
    values = _extract_in_values(str(constraint.sqltext))
    assert values == set(ChatEscalation.allowed_priorities())


def test_escalation_status_check_matches_python_enum() -> None:
    constraint = _get_check_constraint(ChatEscalation, "ck_chat_escalations_status")
    values = _extract_in_values(str(constraint.sqltext))
    assert values == set(ChatEscalation.allowed_statuses())
