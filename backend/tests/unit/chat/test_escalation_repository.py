"""Unit-тесты ChatRepository.create_escalation (E3.6 #71)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.chat.models import ChatSession
from src.api.chat.repository import ChatRepository


def _make_session(user_id: object = None) -> ChatSession:
    s = ChatSession()
    s.id = uuid4()
    s.user_id = user_id  # type: ignore[assignment]
    s.session_token = uuid4()
    s.scope = "tenant" if user_id is not None else "guest"
    s.context = {}
    s.created_at = datetime.now(UTC) - timedelta(hours=1)
    s.expires_at = datetime.now(UTC) + timedelta(hours=12)
    s.deleted_at = None
    return s


@pytest.mark.asyncio
async def test_create_escalation_owner_match_returns_escalation() -> None:
    target = _make_session(user_id=uuid4())
    result_session = MagicMock()
    result_session.scalar_one_or_none.return_value = target
    session = MagicMock()
    session.execute = AsyncMock(return_value=result_session)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()

    repo = ChatRepository(session)
    escalation = await repo.create_escalation(
        target.id,
        user_id=target.user_id,
        reason="плохой ответ",
        priority="high",
    )
    assert escalation is not None
    assert escalation.session_id == target.id
    assert escalation.reason == "плохой ответ"
    assert escalation.priority == "high"
    assert escalation.requested_by_user_id == target.user_id


@pytest.mark.asyncio
@pytest.mark.security
async def test_create_escalation_session_not_owned_returns_none() -> None:
    """Owner-gate: scope не видит session → None, без SQL INSERT."""
    result_session = MagicMock()
    result_session.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result_session)
    session.add = MagicMock()

    repo = ChatRepository(session)
    result = await repo.create_escalation(uuid4(), user_id=uuid4(), reason="x", priority="normal")
    assert result is None
    # Только 1 SQL (gate). add не вызван.
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_escalation_without_identifiers_returns_none() -> None:
    """Без user_id и session_token → get_session_by_owner returns None
    немедленно (security guard E3.1) → None."""
    session = MagicMock()
    session.execute = AsyncMock()  # Won't be called
    session.add = MagicMock()

    repo = ChatRepository(session)
    result = await repo.create_escalation(uuid4())
    assert result is None
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_create_escalation_default_priority_normal_and_anon_user_null() -> None:
    """Без user_id (anon session_token) → requested_by_user_id=None.
    Default priority='normal' если не передан."""
    target = _make_session(user_id=None)  # anon
    result_session = MagicMock()
    result_session.scalar_one_or_none.return_value = target
    session = MagicMock()
    session.execute = AsyncMock(return_value=result_session)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()

    repo = ChatRepository(session)
    escalation = await repo.create_escalation(
        target.id,
        session_token=target.session_token,
    )
    assert escalation is not None
    assert escalation.requested_by_user_id is None
    assert escalation.priority == "normal"
    assert escalation.reason is None
