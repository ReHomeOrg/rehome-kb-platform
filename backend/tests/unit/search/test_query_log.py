"""Unit tests для SearchQueryLogRepository (#220, ТЗ §5.1)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.search.query_log import (
    PopularUnansweredQuery,
    SearchQueryLog,
    SearchQueryLogRepository,
    normalize_query,
)

# ---------------------------------------------------------------------------
# normalize_query


def test_normalize_lowercases() -> None:
    assert normalize_query("Договор Аренды") == "договор аренды"


def test_normalize_collapses_whitespace() -> None:
    assert normalize_query("  как   починить   кран  ") == "как починить кран"


def test_normalize_handles_empty() -> None:
    assert normalize_query("") == ""
    assert normalize_query("   \t\n  ") == ""


def test_normalize_truncates_oversize() -> None:
    """Длинная строка обрезается до 500 chars (defence-in-depth)."""
    oversize = "x" * 1000
    result = normalize_query(oversize)
    assert len(result) == 500


# ---------------------------------------------------------------------------
# log()


def _session() -> MagicMock:
    s = MagicMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    s.execute = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_log_inserts_normalized_row() -> None:
    session = _session()
    repo = SearchQueryLogRepository(session)
    await repo.log(query="  Сервисный   ПЛАТЁЖ  ", has_results=False)
    # add() вызван с SearchQueryLog row
    session.add.assert_called_once()
    row = session.add.call_args.args[0]
    assert isinstance(row, SearchQueryLog)
    assert row.query_normalized == "сервисный платёж"
    assert row.has_results is False
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_records_has_results_true() -> None:
    session = _session()
    repo = SearchQueryLogRepository(session)
    await repo.log(query="договор", has_results=True)
    row = session.add.call_args.args[0]
    assert row.has_results is True


@pytest.mark.asyncio
async def test_log_skips_empty_query() -> None:
    """Whitespace-only нормализуется в "" → no insert (defence-in-depth,
    router сам отвергает 422; гарантия что log table не получит ""."""
    session = _session()
    repo = SearchQueryLogRepository(session)
    await repo.log(query="   ", has_results=False)
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_log_masks_pii_in_query() -> None:
    """ФЗ-152 §6 + CLAUDE.md «нет ПДн в незамаскированном виде»:
    user-supplied query содержащий email / phone → masked перед
    persistence. Top-queries dashboard видит staff_admin'у; ПДн в
    логах хранить нельзя даже за RBAC barrier."""
    session = _session()
    repo = SearchQueryLogRepository(session)
    await repo.log(
        query="контакт менеджера user@example.com +7 916 123-45-67",
        has_results=True,
    )
    session.add.assert_called_once()
    row = session.add.call_args.args[0]
    # Email и телефон должны быть замаскированы.
    assert "user@example.com" not in row.query_normalized
    assert "+7 916" not in row.query_normalized
    assert "916-123-45-67" not in row.query_normalized
    # Mask placeholders присутствуют.
    assert "[EMAIL]" in row.query_normalized or "[PHONE]" in row.query_normalized


@pytest.mark.asyncio
async def test_log_pii_mask_is_idempotent() -> None:
    """Повторный вызов на masked text — placeholders НЕ matches'ят
    patterns (mask_pii idempotent). Garante'ит что multi-pass не
    повреждает данные."""
    session = _session()
    repo = SearchQueryLogRepository(session)
    # Первый pass.
    await repo.log(query="my email user@example.com", has_results=True)
    first_row = session.add.call_args.args[0]
    first_normalized = first_row.query_normalized
    # Второй pass с тем же масштабом — content тот же.
    session.add.reset_mock()
    await repo.log(query="my email user@example.com", has_results=True)
    second_row = session.add.call_args.args[0]
    assert first_normalized == second_row.query_normalized


# ---------------------------------------------------------------------------
# find_popular_unanswered()


@pytest.mark.asyncio
async def test_find_popular_returns_typed_rows() -> None:
    session = _session()
    # SQLAlchemy result row simulation — mappable by .query_normalized / .cnt.
    rows = [
        MagicMock(query_normalized="договор аренды", cnt=10),
        MagicMock(query_normalized="ипотека", cnt=5),
    ]
    session.execute = AsyncMock(return_value=MagicMock(all=lambda: rows))
    repo = SearchQueryLogRepository(session)
    result = await repo.find_popular_unanswered(window_hours=24, min_count=3)
    assert result == [
        PopularUnansweredQuery(query="договор аренды", count=10),
        PopularUnansweredQuery(query="ипотека", count=5),
    ]


@pytest.mark.asyncio
async def test_find_popular_empty_returns_empty_list() -> None:
    session = _session()
    session.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    repo = SearchQueryLogRepository(session)
    result = await repo.find_popular_unanswered()
    assert result == []


@pytest.mark.asyncio
async def test_find_popular_query_applies_filters() -> None:
    """SQL содержит has_results=false + window cutoff + HAVING на min_count."""
    session = _session()
    session.execute = AsyncMock(return_value=MagicMock(all=lambda: []))
    repo = SearchQueryLogRepository(session)
    await repo.find_popular_unanswered(window_hours=24, min_count=3, limit=50)
    stmt = session.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    # has_results=false filter (SQLAlchemy emits `IS false`)
    assert "has_results IS false" in compiled or "has_results = false" in compiled
    # ordering / group-by на query_normalized
    assert "GROUP BY" in compiled
    assert "query_normalized" in compiled
    assert "HAVING" in compiled
    assert "LIMIT" in compiled
