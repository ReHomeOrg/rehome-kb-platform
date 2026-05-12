"""Unit-тесты TagRepository.

Проверяем (ADR-0003 critical invariant):
1. SQL содержит `access_level IN (...)` и `status = 'PUBLISHED'`.
2. Пустой access_levels → ранний return (`[]`) без SQL.
3. `q` → ILIKE substring c escape; `q=None` → нет ILIKE clause.
4. ORDER BY `COUNT(*) DESC, name ASC`.
5. LIMIT bind param ok.
6. GROUP BY на распакованных тегах (jsonb_array_elements_text).
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.auth.scope import AccessLevel
from src.api.tags.repository import TagRepository, _escape_ilike


@pytest.fixture
def empty_session() -> Any:
    """Session, чей execute возвращает empty rows."""
    result = MagicMock()
    result.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# _escape_ilike helpers


def test_escape_ilike_passes_plain_text_through() -> None:
    assert _escape_ilike("договор") == "договор"


def test_escape_ilike_escapes_percent_and_underscore() -> None:
    assert _escape_ilike("a%b_c") == "a\\%b\\_c"


def test_escape_ilike_escapes_backslash_first() -> None:
    """Backslash должен экранироваться ПЕРЕД `%`/`_`, иначе вставленные
    escape-последовательности (`\\%`/`\\_`) сами начнут экранироваться."""
    assert _escape_ilike("a\\b") == "a\\\\b"


def test_escape_ilike_empty_returns_empty() -> None:
    assert _escape_ilike("") == ""


# ---------------------------------------------------------------------------
# list_tags — ADR-0003 invariants


@pytest.mark.asyncio
async def test_list_tags_empty_access_levels_returns_empty_without_sql(
    empty_session: Any,
) -> None:
    """`IN ()` в Postgres всегда false — но мы возвращаем раньше, чтобы
    не гонять заведомо пустой SQL."""
    repo = TagRepository(empty_session)
    result = await repo.list_tags(frozenset())
    assert result == []
    empty_session.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.security
async def test_list_tags_sql_includes_access_level_and_status_filter(
    empty_session: Any,
) -> None:
    """ADR-0003: финальный SQL обязан содержать `access_level IN (...)`
    И `status = 'PUBLISHED'`. Если будущий рефакторинг вырежет фильтр —
    тест поймает по тексту."""
    repo = TagRepository(empty_session)
    await repo.list_tags(frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED}))

    called_stmt = empty_session.execute.call_args[0][0]
    compiled = called_stmt.compile()
    sql = str(compiled).lower()
    params = compiled.params

    assert "status" in sql
    assert "access_level in" in sql
    # access_level → expanding bind: значение приходит как list/tuple.
    bind_param = next(v for k, v in params.items() if k.startswith("access_level_"))
    assert set(bind_param) == {"PUBLIC", "LOGGED"}
    # status fixed string
    assert any(v == "PUBLISHED" for v in params.values())


@pytest.mark.asyncio
async def test_list_tags_sql_uses_jsonb_unnest_and_group_by(
    empty_session: Any,
) -> None:
    """Источник тегов — jsonb_array_elements_text(articles.tags) с GROUP BY."""
    repo = TagRepository(empty_session)
    await repo.list_tags(frozenset({AccessLevel.PUBLIC}))

    called_stmt = empty_session.execute.call_args[0][0]
    sql = str(called_stmt.compile()).lower()
    assert "jsonb_array_elements_text" in sql
    assert "group by" in sql
    assert "count(" in sql


@pytest.mark.asyncio
async def test_list_tags_sql_sorts_by_count_desc_then_name_asc(
    empty_session: Any,
) -> None:
    repo = TagRepository(empty_session)
    await repo.list_tags(frozenset({AccessLevel.PUBLIC}))

    sql = str(empty_session.execute.call_args[0][0].compile()).lower()
    order_by_idx = sql.index("order by")
    order_clause = sql[order_by_idx:]
    # article_count DESC появляется ДО tag ASC
    assert "article_count desc" in order_clause
    count_pos = order_clause.index("article_count desc")
    name_pos = order_clause.index(" asc")
    assert count_pos < name_pos


@pytest.mark.asyncio
async def test_list_tags_default_limit_50_in_sql(empty_session: Any) -> None:
    repo = TagRepository(empty_session)
    await repo.list_tags(frozenset({AccessLevel.PUBLIC}))
    compiled = empty_session.execute.call_args[0][0].compile()
    params = compiled.params
    assert 50 in params.values()


@pytest.mark.asyncio
async def test_list_tags_custom_limit_propagates_to_sql(
    empty_session: Any,
) -> None:
    repo = TagRepository(empty_session)
    await repo.list_tags(frozenset({AccessLevel.PUBLIC}), limit=7)
    params = empty_session.execute.call_args[0][0].compile().params
    assert 7 in params.values()


@pytest.mark.asyncio
async def test_list_tags_no_q_does_not_add_ilike(
    empty_session: Any,
) -> None:
    repo = TagRepository(empty_session)
    await repo.list_tags(frozenset({AccessLevel.PUBLIC}))
    sql = str(empty_session.execute.call_args[0][0].compile()).lower()
    assert " ilike " not in sql
    assert " like lower(" not in sql


@pytest.mark.asyncio
async def test_list_tags_with_q_adds_ilike_with_escape(
    empty_session: Any,
) -> None:
    repo = TagRepository(empty_session)
    await repo.list_tags(frozenset({AccessLevel.PUBLIC}), q="договор")
    compiled = empty_session.execute.call_args[0][0].compile()
    sql = str(compiled).lower()
    params = compiled.params
    # На default dialect (нет real Postgres) `.ilike()` рендерится как
    # `LOWER(x) LIKE LOWER(y)`; на postgresql — как `ILIKE`. Проверяем
    # семантическое наличие case-insensitive substring match (без жёсткой
    # привязки к имени column-alias, которое SQLA генерирует).
    assert " ilike " in sql or " like lower(" in sql
    # bind содержит pattern '%договор%' (substring match)
    assert any(isinstance(v, str) and v == "%договор%" for v in params.values())


@pytest.mark.asyncio
async def test_list_tags_ilike_escapes_user_wildcards(
    empty_session: Any,
) -> None:
    """`q='%'` НЕ должно стать match-all — пользовательский `%` экранируется."""
    repo = TagRepository(empty_session)
    await repo.list_tags(frozenset({AccessLevel.PUBLIC}), q="50%")
    params = empty_session.execute.call_args[0][0].compile().params
    # Ожидаем pattern '%50\\%%' (literal `%` в середине, wildcard'ы по краям)
    assert any(isinstance(v, str) and v == "%50\\%%" for v in params.values())


@pytest.mark.asyncio
async def test_list_tags_returns_rows_as_tuples() -> None:
    rows = [MagicMock(), MagicMock()]
    rows[0].name = "договор"
    rows[0].article_count = 3
    rows[1].name = "аренда"
    rows[1].article_count = 1
    result = MagicMock()
    result.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    repo = TagRepository(session)
    out = await repo.list_tags(frozenset({AccessLevel.PUBLIC}))
    assert out == [("договор", 3), ("аренда", 1)]
