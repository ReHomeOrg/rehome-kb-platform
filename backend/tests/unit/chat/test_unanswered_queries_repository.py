"""Unit tests for ChatUnansweredQueryRepository (2026-05-29)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.chat.unanswered_queries import (
    QUERY_MASKED_MAX_CHARS,
    ChatUnansweredQuery,
    ChatUnansweredQueryRepository,
)


def _session() -> MagicMock:
    s = MagicMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    s.execute = AsyncMock()
    return s


def _row(
    *,
    status: str = "NEW",
    query_masked: str = "test query",
    author_sub: str = "user-1",
    attached_question_id: object = None,
) -> SimpleNamespace:
    """Plain object с attributes, имитирующий ORM row."""
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        query_masked=query_masked,
        author_sub=author_sub,
        chat_session_id=uuid4(),
        attached_question_id=attached_question_id,
        attached_article_slug=None,
        attached_at=None,
        dismiss_reason=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# record


@pytest.mark.asyncio
async def test_record_masks_pii() -> None:
    session = _session()
    repo = ChatUnansweredQueryRepository(session)
    await repo.record(
        query="контакт менеджера user@example.com +7 916 123-45-67",
        author_sub="user-1",
        chat_session_id=uuid4(),
    )
    session.add.assert_called_once()
    row = session.add.call_args.args[0]
    assert isinstance(row, ChatUnansweredQuery)
    assert "user@example.com" not in row.query_masked
    assert "+7 916" not in row.query_masked
    assert "[EMAIL]" in row.query_masked or "[PHONE]" in row.query_masked
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_truncates_oversize_query() -> None:
    session = _session()
    repo = ChatUnansweredQueryRepository(session)
    long = "x" * 1000
    await repo.record(query=long, author_sub="u", chat_session_id=None)
    row = session.add.call_args.args[0]
    assert len(row.query_masked) == QUERY_MASKED_MAX_CHARS


@pytest.mark.asyncio
async def test_record_skips_empty_query() -> None:
    """Whitespace-only после mask_pii — no insert."""
    session = _session()
    repo = ChatUnansweredQueryRepository(session)
    result = await repo.record(query="   \n  ", author_sub="u", chat_session_id=None)
    assert result is None
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_persists_author_and_session() -> None:
    session = _session()
    repo = ChatUnansweredQueryRepository(session)
    sid = uuid4()
    await repo.record(query="how to do X", author_sub="user-42", chat_session_id=sid)
    row = session.add.call_args.args[0]
    assert row.author_sub == "user-42"
    assert row.chat_session_id == sid


# ---------------------------------------------------------------------------
# list_admin


@pytest.mark.asyncio
async def test_list_admin_returns_rows_and_total() -> None:
    session = _session()
    rows = [_row(), _row()]

    # Mock execute returns sequential: rows query first, count query second.
    rows_result = MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: rows)))
    count_result = MagicMock(scalar_one=lambda: 7)
    session.execute = AsyncMock(side_effect=[rows_result, count_result])

    repo = ChatUnansweredQueryRepository(session)
    result_rows, total = await repo.list_admin(status_filter=None, limit=10, offset=0)
    assert result_rows == rows
    assert total == 7


# ---------------------------------------------------------------------------
# mark_attached


@pytest.mark.asyncio
async def test_mark_attached_sets_status_and_fields() -> None:
    session = _session()
    row = _row(status="NEW")
    repo = ChatUnansweredQueryRepository(session)
    repo.get_by_id = AsyncMock(return_value=row)  # type: ignore[method-assign]

    question_id = uuid4()
    updated = await repo.mark_attached(
        row.id,
        attached_question_id=question_id,
        attached_article_slug="my-slug",
    )
    assert updated is not None
    assert updated.status == "ATTACHED"
    assert updated.attached_question_id == question_id
    assert updated.attached_article_slug == "my-slug"
    assert updated.attached_at is not None


@pytest.mark.asyncio
async def test_mark_attached_returns_none_if_not_found() -> None:
    session = _session()
    repo = ChatUnansweredQueryRepository(session)
    repo.get_by_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    result = await repo.mark_attached(
        uuid4(), attached_question_id=uuid4(), attached_article_slug="x"
    )
    assert result is None


# ---------------------------------------------------------------------------
# mark_dismissed


@pytest.mark.asyncio
async def test_mark_dismissed_sets_status_and_reason() -> None:
    session = _session()
    row = _row(status="NEW")
    repo = ChatUnansweredQueryRepository(session)
    repo.get_by_id = AsyncMock(return_value=row)  # type: ignore[method-assign]

    updated = await repo.mark_dismissed(row.id, reason="off-topic")
    assert updated is not None
    assert updated.status == "DISMISSED"
    assert updated.dismiss_reason == "off-topic"


@pytest.mark.asyncio
async def test_mark_dismissed_blocks_attached() -> None:
    """ATTACHED row — mark_dismissed возвращает row без изменения; router
    обрабатывает 409."""
    session = _session()
    row = _row(status="ATTACHED")
    original_status = row.status
    repo = ChatUnansweredQueryRepository(session)
    repo.get_by_id = AsyncMock(return_value=row)  # type: ignore[method-assign]

    result = await repo.mark_dismissed(row.id, reason="late")
    assert result is row
    assert result is not None
    assert result.status == original_status  # unchanged


@pytest.mark.asyncio
async def test_mark_dismissed_returns_none_if_not_found() -> None:
    session = _session()
    repo = ChatUnansweredQueryRepository(session)
    repo.get_by_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    result = await repo.mark_dismissed(uuid4(), reason=None)
    assert result is None


# ---------------------------------------------------------------------------
# find_top_normalized


def _bucket(
    normalized: str,
    count: int,
    *,
    first_offset_h: int = 24,
    last_offset_h: int = 1,
) -> SimpleNamespace:
    """Имитирует aggregator row."""
    now = datetime.now(UTC)
    return SimpleNamespace(
        normalized=normalized,
        cnt=count,
        first_seen=now - timedelta(hours=first_offset_h),
        last_seen=now - timedelta(hours=last_offset_h),
    )


@pytest.mark.asyncio
async def test_find_top_normalized_returns_buckets() -> None:
    """Repo возвращает (normalized, count, first_seen, last_seen) tuples."""
    session = _session()
    buckets = [
        _bucket("сервисный сбор", 7),
        _bucket("оплата", 3),
        _bucket("кэдо", 2),
    ]
    rows_result = MagicMock(all=MagicMock(return_value=buckets))
    session.execute = AsyncMock(return_value=rows_result)

    repo = ChatUnansweredQueryRepository(session)
    result = await repo.find_top_normalized(window_hours=24, limit=10)
    assert len(result) == 3
    normalized_0, count_0, first_0, last_0 = result[0]
    assert normalized_0 == "сервисный сбор"
    assert count_0 == 7
    assert isinstance(first_0, datetime)
    assert isinstance(last_0, datetime)
    assert first_0 <= last_0


@pytest.mark.asyncio
async def test_find_top_normalized_empty_result() -> None:
    session = _session()
    rows_result = MagicMock(all=MagicMock(return_value=[]))
    session.execute = AsyncMock(return_value=rows_result)

    repo = ChatUnansweredQueryRepository(session)
    result = await repo.find_top_normalized(window_hours=24, limit=10)
    assert result == []


@pytest.mark.asyncio
async def test_find_top_normalized_default_status_is_new() -> None:
    """По умолчанию метод фильтрует на NEW; SQL должен содержать WHERE на status."""
    session = _session()
    rows_result = MagicMock(all=MagicMock(return_value=[]))
    session.execute = AsyncMock(return_value=rows_result)

    repo = ChatUnansweredQueryRepository(session)
    await repo.find_top_normalized(window_hours=24, limit=10)

    # Стейтмент передан в execute — проверяем что compile содержит status filter.
    stmt = session.execute.await_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "status" in compiled
    assert "NEW" in compiled


@pytest.mark.asyncio
async def test_find_top_normalized_status_none_skips_filter() -> None:
    """status_filter=None — нет фильтра по статусу в SQL."""
    session = _session()
    rows_result = MagicMock(all=MagicMock(return_value=[]))
    session.execute = AsyncMock(return_value=rows_result)

    repo = ChatUnansweredQueryRepository(session)
    await repo.find_top_normalized(window_hours=24, limit=10, status_filter=None)

    stmt = session.execute.await_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    # Допустим SELECT может ссылаться на column "status" в `lower(query_masked)`
    # alias / нет; ключевая проверка — нет equality WHERE на status'е.
    assert "status = 'NEW'" not in compiled
    assert "status = 'ATTACHED'" not in compiled


@pytest.mark.asyncio
async def test_find_top_normalized_window_cutoff_in_sql() -> None:
    """Окно применяется через created_at >= cutoff."""
    session = _session()
    rows_result = MagicMock(all=MagicMock(return_value=[]))
    session.execute = AsyncMock(return_value=rows_result)

    repo = ChatUnansweredQueryRepository(session)
    await repo.find_top_normalized(window_hours=72, limit=10)
    stmt = session.execute.await_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "created_at" in compiled


@pytest.mark.asyncio
async def test_find_top_normalized_uses_lower_normalization() -> None:
    """Группировка по lower(query_masked) — case-insensitive aggregation."""
    session = _session()
    rows_result = MagicMock(all=MagicMock(return_value=[]))
    session.execute = AsyncMock(return_value=rows_result)

    repo = ChatUnansweredQueryRepository(session)
    await repo.find_top_normalized(window_hours=24, limit=10)
    stmt = session.execute.await_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "lower(" in compiled.lower()
    assert "query_masked" in compiled
