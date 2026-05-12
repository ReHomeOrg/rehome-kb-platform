"""Unit-тесты ChatRepository (E3.1 #61).

Покрывает двойную авторизацию (user_id ИЛИ session_token):
- create_session: TTL anon (24h) vs authorized (30d), session_token всегда.
- get_session_by_owner: оба identifier → ANY-match, один → exact match,
  ни одного → None (security guard, no SQL).
- get_session_by_owner: cross-user mask (wrong user_id → None).
- get_session_by_owner: expired / deleted → None.
- soft_delete_session: устанавливает deleted_at, идемпотентно.
- list_messages: gate через get_session_by_owner; sort ASC.
- append_message: assumed-internal (без owner check).
- set_feedback: JSONB update.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.chat.models import ChatMessage, ChatSession
from src.api.chat.repository import (
    ANON_SESSION_TTL,
    AUTH_SESSION_TTL,
    ChatRepository,
)


def _make_session(
    user_id: object = None,
    session_token: object = None,
    deleted: bool = False,
    expires_delta: timedelta = timedelta(hours=12),
) -> ChatSession:
    s = ChatSession()
    s.id = uuid4()
    s.user_id = user_id  # type: ignore[assignment]
    s.session_token = session_token or uuid4()  # type: ignore[assignment]
    s.scope = "guest"
    s.context = {}
    s.created_at = datetime.now(UTC) - timedelta(hours=1)
    s.expires_at = datetime.now(UTC) + expires_delta
    s.deleted_at = datetime.now(UTC) if deleted else None
    return s


def _make_message(session_id: object, role: str = "user", content: str = "hi") -> ChatMessage:
    m = ChatMessage()
    m.id = uuid4()
    m.session_id = session_id  # type: ignore[assignment]
    m.role = role
    m.content = content
    m.citations = []
    m.feedback = None
    m.token_count = None
    m.duration_ms = None
    m.created_at = datetime.now(UTC)
    return m


def _session_with_result(scalar: object = None, scalars_all: list[object] | None = None) -> Any:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    if scalars_all is not None:
        result.scalars.return_value.all.return_value = scalars_all
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.commit = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# create_session


@pytest.mark.asyncio
async def test_create_session_anon_uses_24h_ttl() -> None:
    """ANON_SESSION_TTL — 24h."""
    session = _session_with_result()
    repo = ChatRepository(session)
    result = await repo.create_session(user_id=None, scope="guest")
    assert result.user_id is None
    assert result.session_token is not None
    delta = result.expires_at - datetime.now(UTC)
    # ~24h ± malloc on jitter (test isn't time-precise)
    assert (
        ANON_SESSION_TTL - timedelta(seconds=5) <= delta <= ANON_SESSION_TTL + timedelta(seconds=5)
    )


@pytest.mark.asyncio
async def test_create_session_authorized_uses_30d_ttl() -> None:
    session = _session_with_result()
    repo = ChatRepository(session)
    user_id = uuid4()
    result = await repo.create_session(user_id=user_id, scope="tenant")
    assert result.user_id == user_id
    delta = result.expires_at - datetime.now(UTC)
    assert (
        AUTH_SESSION_TTL - timedelta(seconds=5) <= delta <= AUTH_SESSION_TTL + timedelta(seconds=5)
    )


@pytest.mark.asyncio
async def test_create_session_always_generates_session_token() -> None:
    """Даже для authorized — session_token не None (cross-device continuation)."""
    session = _session_with_result()
    repo = ChatRepository(session)
    result = await repo.create_session(user_id=uuid4(), scope="tenant")
    assert result.session_token is not None


# ---------------------------------------------------------------------------
# get_session_by_owner — security guard


@pytest.mark.asyncio
@pytest.mark.security
async def test_get_session_neither_identifier_returns_none_without_sql() -> None:
    """Security guard: без user_id и без session_token — return None немедленно."""
    session = _session_with_result()
    repo = ChatRepository(session)
    result = await repo.get_session_by_owner(uuid4())
    assert result is None
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_get_session_user_id_matching_returns_session() -> None:
    target = _make_session(user_id=uuid4())
    session = _session_with_result(scalar=target)
    repo = ChatRepository(session)
    result = await repo.get_session_by_owner(target.id, user_id=target.user_id)
    assert result is target


@pytest.mark.asyncio
async def test_get_session_session_token_matching_returns_session() -> None:
    target = _make_session(session_token=uuid4())
    session = _session_with_result(scalar=target)
    repo = ChatRepository(session)
    result = await repo.get_session_by_owner(target.id, session_token=target.session_token)
    assert result is target


@pytest.mark.asyncio
async def test_get_session_both_identifiers_passed_uses_or_clause() -> None:
    """Если переданы оба — SQL содержит OR clause."""
    target = _make_session(user_id=uuid4(), session_token=uuid4())
    session = _session_with_result(scalar=target)
    repo = ChatRepository(session)
    await repo.get_session_by_owner(
        target.id, user_id=target.user_id, session_token=target.session_token
    )
    sql = str(session.execute.call_args[0][0].compile()).lower()
    assert " or " in sql


@pytest.mark.asyncio
@pytest.mark.security
async def test_get_session_wrong_user_returns_none() -> None:
    """Cross-user mask: SQL не находит → None."""
    session = _session_with_result(scalar=None)
    repo = ChatRepository(session)
    result = await repo.get_session_by_owner(uuid4(), user_id=uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_session_sql_filters_expired_and_deleted() -> None:
    session = _session_with_result()
    repo = ChatRepository(session)
    await repo.get_session_by_owner(uuid4(), user_id=uuid4())
    sql = str(session.execute.call_args[0][0].compile()).lower()
    assert "deleted_at is null" in sql
    assert "expires_at >" in sql


# ---------------------------------------------------------------------------
# soft_delete_session


@pytest.mark.asyncio
async def test_soft_delete_existing_session_returns_true() -> None:
    target = _make_session(user_id=uuid4())
    session = _session_with_result(scalar=target)
    repo = ChatRepository(session)
    result = await repo.soft_delete_session(target.id, user_id=target.user_id)
    assert result is True
    assert target.deleted_at is not None


@pytest.mark.asyncio
async def test_soft_delete_session_not_owned_returns_false() -> None:
    """Owner mismatch → False (через get_session_by_owner gate)."""
    session = _session_with_result(scalar=None)
    repo = ChatRepository(session)
    result = await repo.soft_delete_session(uuid4(), user_id=uuid4())
    assert result is False


@pytest.mark.asyncio
async def test_soft_delete_without_identifiers_returns_false() -> None:
    session = _session_with_result()
    repo = ChatRepository(session)
    result = await repo.soft_delete_session(uuid4())
    assert result is False
    session.execute.assert_not_called()


# ---------------------------------------------------------------------------
# list_messages — owner-gated


@pytest.mark.asyncio
async def test_list_messages_without_identifiers_returns_empty() -> None:
    session = _session_with_result()
    repo = ChatRepository(session)
    result = await repo.list_messages(uuid4())
    assert result == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_list_messages_owner_mismatch_returns_empty() -> None:
    """get_session_by_owner вернул None → [] (mask cross-user access)."""
    # Первый execute — get_session_by_owner → None
    result_a = MagicMock()
    result_a.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result_a)
    repo = ChatRepository(session)
    out = await repo.list_messages(uuid4(), user_id=uuid4())
    assert out == []
    # Только один SQL (gate); query на messages не выполнялся
    assert session.execute.call_count == 1


@pytest.mark.asyncio
async def test_list_messages_owner_match_returns_messages() -> None:
    target = _make_session(user_id=uuid4())
    msg1 = _make_message(target.id, role="user", content="hi")
    msg2 = _make_message(target.id, role="assistant", content="hello")

    result_session = MagicMock()
    result_session.scalar_one_or_none.return_value = target
    result_msgs = MagicMock()
    result_msgs.scalars.return_value.all.return_value = [msg1, msg2]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[result_session, result_msgs])
    repo = ChatRepository(session)
    out = await repo.list_messages(target.id, user_id=target.user_id)
    assert out == [msg1, msg2]


@pytest.mark.asyncio
async def test_list_messages_sql_orders_by_created_at_asc() -> None:
    target = _make_session(user_id=uuid4())
    result_session = MagicMock()
    result_session.scalar_one_or_none.return_value = target
    result_msgs = MagicMock()
    result_msgs.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[result_session, result_msgs])
    repo = ChatRepository(session)
    await repo.list_messages(target.id, user_id=target.user_id)
    # Второй вызов — select messages
    sql = str(session.execute.call_args_list[1][0][0].compile()).lower()
    assert "order by chat_messages.created_at asc" in sql


# ---------------------------------------------------------------------------
# append_message + set_feedback (internal helpers)


@pytest.mark.asyncio
async def test_append_message_adds_to_session() -> None:
    session = _session_with_result()
    repo = ChatRepository(session)
    msg = await repo.append_message(
        uuid4(),
        role="assistant",
        content="answer",
        citations=[{"type": "article", "id": str(uuid4()), "title": "X"}],
        token_count=42,
        duration_ms=120,
    )
    assert msg.role == "assistant"
    assert msg.content == "answer"
    assert msg.token_count == 42
    session.add.assert_called_once_with(msg)


@pytest.mark.asyncio
async def test_set_feedback_owner_match_updates_message() -> None:
    """E3.5: set_feedback с owner-match → updates feedback и returns message."""
    target_session = _make_session(user_id=uuid4())
    msg = _make_message(target_session.id, role="assistant", content="x")

    # 2 SELECT: get_session_by_owner → message scoped to session
    result_session = MagicMock()
    result_session.scalar_one_or_none.return_value = target_session
    result_msg = MagicMock()
    result_msg.scalar_one_or_none.return_value = msg
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[result_session, result_msg])
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    repo = ChatRepository(session)
    result = await repo.set_feedback(
        msg.id,
        session_id=target_session.id,
        user_id=target_session.user_id,
        rating="up",
        comment="great",
    )
    assert result is msg
    assert msg.feedback == {"rating": "up", "comment": "great"}


@pytest.mark.asyncio
async def test_set_feedback_no_comment_omits_field() -> None:
    target_session = _make_session(user_id=uuid4())
    msg = _make_message(target_session.id)
    result_session = MagicMock()
    result_session.scalar_one_or_none.return_value = target_session
    result_msg = MagicMock()
    result_msg.scalar_one_or_none.return_value = msg
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[result_session, result_msg])
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    repo = ChatRepository(session)
    await repo.set_feedback(
        msg.id,
        session_id=target_session.id,
        user_id=target_session.user_id,
        rating="down",
    )
    assert msg.feedback == {"rating": "down"}


@pytest.mark.asyncio
@pytest.mark.security
async def test_set_feedback_session_not_owned_returns_none() -> None:
    """ADR-0003 adaptation: session не принадлежит caller'у → None (no DB)."""
    session = _session_with_result(scalar=None)  # get_session_by_owner → None
    repo = ChatRepository(session)
    result = await repo.set_feedback(
        uuid4(),
        session_id=uuid4(),
        user_id=uuid4(),
        rating="up",
    )
    assert result is None
    # Только 1 SQL (gate); SELECT message не выполнялся
    assert session.execute.call_count == 1


@pytest.mark.asyncio
async def test_set_feedback_message_not_found_returns_none() -> None:
    """Session ok, но message_id не существует → None."""
    target_session = _make_session(user_id=uuid4())
    result_session = MagicMock()
    result_session.scalar_one_or_none.return_value = target_session
    result_msg = MagicMock()
    result_msg.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[result_session, result_msg])
    repo = ChatRepository(session)
    result = await repo.set_feedback(
        uuid4(),
        session_id=target_session.id,
        user_id=target_session.user_id,
        rating="up",
    )
    assert result is None


@pytest.mark.asyncio
@pytest.mark.security
async def test_set_feedback_sql_includes_session_id_scope() -> None:
    """Cross-session защита: SELECT message с фильтром по session_id."""
    target_session = _make_session(user_id=uuid4())
    result_session = MagicMock()
    result_session.scalar_one_or_none.return_value = target_session
    result_msg = MagicMock()
    result_msg.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[result_session, result_msg])
    repo = ChatRepository(session)
    await repo.set_feedback(
        uuid4(),
        session_id=target_session.id,
        user_id=target_session.user_id,
        rating="up",
    )
    # 2nd execute — SELECT message; SQL содержит session_id фильтр
    sql = str(session.execute.call_args_list[1][0][0].compile()).lower()
    assert "session_id" in sql
    assert "chat_messages.id" in sql


@pytest.mark.asyncio
async def test_set_feedback_overwrites_existing_feedback() -> None:
    """Idempotent: повторный set с другим rating перезаписывает."""
    target_session = _make_session(user_id=uuid4())
    msg = _make_message(target_session.id)
    msg.feedback = {"rating": "up", "comment": "good"}  # уже есть
    result_session = MagicMock()
    result_session.scalar_one_or_none.return_value = target_session
    result_msg = MagicMock()
    result_msg.scalar_one_or_none.return_value = msg
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[result_session, result_msg])
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    repo = ChatRepository(session)
    await repo.set_feedback(
        msg.id,
        session_id=target_session.id,
        user_id=target_session.user_id,
        rating="down",
        comment="bad",
    )
    assert msg.feedback == {"rating": "down", "comment": "bad"}
