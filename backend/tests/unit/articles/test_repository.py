"""Unit-тесты ArticleRepository.

Проверяем, что:
1. SQL фильтр включает access_level (ADR-0003 critical invariant) —
   для `get_by_slug` И для `list_filtered`.
2. Возвращаем None / [] если scope не видит ресурсы.
3. SQL генерируется через bind params, не f-string (anti-SQL-injection).
4. `status = 'PUBLISHED'` всегда присутствует в WHERE (DRAFT/ARCHIVED guard).
5. Cursor row-value comparison `(updated_at, id) <` не разворачивается в AND.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from src.api.articles.models import Article
from src.api.articles.repository import ArticleRepository
from src.api.auth.scope import (
    AccessLevel,
    Scope,
    compute_access_levels,
)


@pytest.mark.asyncio
async def test_get_by_slug_returns_article_when_found(
    fake_article: Article,
    session_returning: Callable[[Article | None], Any],
) -> None:
    repo = ArticleRepository(session_returning(fake_article))
    result = await repo.get_by_slug(
        "kak-podpisat-dogovor",
        frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED}),
    )
    assert result is fake_article


@pytest.mark.asyncio
async def test_get_by_slug_returns_none_when_not_found(
    session_returning: Callable[[Article | None], Any],
) -> None:
    repo = ArticleRepository(session_returning(None))
    result = await repo.get_by_slug(
        "nonexistent",
        frozenset({AccessLevel.PUBLIC}),
    )
    assert result is None


@pytest.mark.asyncio
@pytest.mark.security
async def test_get_by_slug_sql_includes_access_level_filter() -> None:
    """ADR-0003: финальный SQL обязан содержать `access_level IN (...)`.

    Если будущая регрессия удалит фильтр — тест поймает её по тексту запроса.
    """
    captured: dict[str, Any] = {}

    async def _capture(stmt: Any) -> Any:
        captured["stmt"] = stmt
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)

    repo = ArticleRepository(session)
    await repo.get_by_slug("any", frozenset({AccessLevel.PUBLIC, AccessLevel.STAFF}))

    sql_text = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "access_level IN" in sql_text
    assert "'PUBLIC'" in sql_text
    assert "'STAFF'" in sql_text
    # Storage-level filter дополнительно фильтрует status:
    assert "status" in sql_text
    assert "'PUBLISHED'" in sql_text


@pytest.mark.asyncio
@pytest.mark.security
async def test_get_by_slug_empty_access_levels_returns_none(
    session_returning: Callable[[Article | None], Any],
) -> None:
    """Empty frozenset → SQL `IN ()` → 0 строк → None (404 в router'е)."""
    # session.execute вернёт scalar_one_or_none() == None для пустого результата.
    repo = ArticleRepository(session_returning(None))
    result = await repo.get_by_slug("anything", frozenset())
    assert result is None


# ============================================================
# list_filtered tests
# ============================================================


def _build_session_returning_rows(rows: list[Article]) -> Any:
    """AsyncSession-мок, возвращающий указанный список через scalars().all()."""
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


async def _capture_list_filtered_sql(**kwargs: Any) -> str:
    """Запускает `list_filtered` с переданными kwargs и возвращает SQL-string.

    `kwargs` обязаны содержать `access_levels`; остальное — опциональные
    фильтры/cursor/limit.
    """
    captured: dict[str, Any] = {}

    async def _capture(stmt: Any) -> Any:
        captured["stmt"] = stmt
        scalars = MagicMock()
        scalars.all.return_value = []
        result = MagicMock()
        result.scalars.return_value = scalars
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    repo = ArticleRepository(session)
    await repo.list_filtered(**kwargs)
    return str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_list_filtered_returns_rows_and_has_more_false(
    fake_article: Article,
) -> None:
    """Меньше limit → has_more=False, без trim."""
    session = _build_session_returning_rows([fake_article])
    repo = ArticleRepository(session)
    rows, has_more = await repo.list_filtered(frozenset({AccessLevel.PUBLIC}), limit=20)
    assert rows == [fake_article]
    assert has_more is False


@pytest.mark.asyncio
async def test_list_filtered_has_more_true_and_trims_to_limit(
    fake_article: Article,
) -> None:
    """SQL запрашивает limit+1; если получили limit+1 → has_more=True, возвращаем limit штук."""
    # Создаём 4 разных Article — limit=3, repo запросит 4, получит 4.
    rows_in = []
    for _ in range(4):
        a = Article()
        a.id = uuid4()
        a.updated_at = datetime(2026, 5, 12, tzinfo=UTC)
        rows_in.append(a)
    session = _build_session_returning_rows(rows_in)
    repo = ArticleRepository(session)
    rows, has_more = await repo.list_filtered(frozenset({AccessLevel.PUBLIC}), limit=3)
    assert len(rows) == 3  # Trim до limit, НЕ 4.
    assert has_more is True


@pytest.mark.asyncio
async def test_list_filtered_empty_returns_empty_no_has_more() -> None:
    session = _build_session_returning_rows([])
    repo = ArticleRepository(session)
    rows, has_more = await repo.list_filtered(frozenset({AccessLevel.PUBLIC}))
    assert rows == []
    assert has_more is False


@pytest.mark.asyncio
@pytest.mark.security
async def test_list_filtered_sql_always_includes_status_published() -> None:
    """SQL-уровень guard: DRAFT/ARCHIVED не утекают в list никогда."""
    sql = await _capture_list_filtered_sql(
        access_levels=frozenset({AccessLevel.PUBLIC}),
    )
    assert "status" in sql
    assert "'PUBLISHED'" in sql


@pytest.mark.asyncio
@pytest.mark.security
@pytest.mark.parametrize(
    "scope",
    [
        Scope.GUEST,
        Scope.TENANT,
        Scope.LANDLORD,
        Scope.AGENT,
        Scope.STAFF_SUPPORT,
        Scope.STAFF_LEGAL,
        Scope.STAFF_HR,
        Scope.STAFF_ADMIN,
    ],
)
async def test_list_filtered_sql_includes_correct_access_levels_per_scope(
    scope: Scope,
) -> None:
    """ADR-0003 critical: SQL содержит ровно те access_levels, что выдал
    `compute_access_levels` для каждого Scope.

    Особо: `staff_admin` НЕ должен получать `HR_RESTRICTED`.
    """
    role_map = {
        Scope.GUEST: [],
        Scope.TENANT: ["tenant"],
        Scope.LANDLORD: ["landlord"],
        Scope.AGENT: ["agent"],
        Scope.STAFF_SUPPORT: ["staff_support"],
        Scope.STAFF_LEGAL: ["staff_legal"],
        Scope.STAFF_HR: ["staff_hr"],
        Scope.STAFF_ADMIN: ["staff_admin"],
    }
    levels = compute_access_levels(role_map[scope])
    sql = await _capture_list_filtered_sql(access_levels=levels)

    assert "access_level IN" in sql
    for lvl in levels:
        assert f"'{lvl.value}'" in sql

    # Guard: уровни, НЕ принадлежащие данному scope, не должны попасть в IN.
    all_levels: set[AccessLevel] = set(AccessLevel.__members__.values())
    forbidden: set[AccessLevel] = all_levels - levels
    # Простая эвристика: ищем `'<LEVEL>'` в SQL — все literal access_level'ы
    # появляются только в нашем IN-клаузе.
    for forbidden_lvl in forbidden:
        assert f"'{forbidden_lvl.value}'" not in sql, (
            f"Scope={scope.value}: access_level={forbidden_lvl.value} утёк в SQL "
            "(ADR-0003 regression)"
        )


@pytest.mark.asyncio
async def test_list_filtered_sql_uses_correct_order_and_limit() -> None:
    sql = await _capture_list_filtered_sql(
        access_levels=frozenset({AccessLevel.PUBLIC}),
        limit=20,
    )
    # ORDER BY updated_at DESC, id DESC
    assert "ORDER BY" in sql
    assert "updated_at DESC" in sql
    assert "id DESC" in sql
    # LIMIT 21 (limit + 1 для has_more detection)
    assert "LIMIT 21" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filter_key", "value"),
    [
        ("category", "rental"),
        ("audience", "tenant"),
        ("language", "ru"),
    ],
)
async def test_list_filtered_sql_includes_optional_filter(filter_key: str, value: str) -> None:
    sql = await _capture_list_filtered_sql(
        access_levels=frozenset({AccessLevel.PUBLIC}),
        **{filter_key: value},
    )
    assert filter_key in sql
    assert f"'{value}'" in sql


@pytest.mark.asyncio
async def test_list_filtered_omits_filter_when_none() -> None:
    """Без явного фильтра — нет соответствующего WHERE-условия."""
    sql = await _capture_list_filtered_sql(
        access_levels=frozenset({AccessLevel.PUBLIC}),
    )
    # Базовые условия есть.
    assert "status" in sql
    assert "access_level IN" in sql
    # Опциональные не подмешаны.
    assert "category =" not in sql
    assert "audience =" not in sql
    assert "language =" not in sql


@pytest.mark.asyncio
async def test_list_filtered_unknown_category_value_still_yields_valid_sql() -> None:
    """Drift OpenAPI: `category=unknown` не падает 500/422; возвращает 200 [].

    SQL компилируется, просто matches 0 строк.
    """
    sql = await _capture_list_filtered_sql(
        access_levels=frozenset({AccessLevel.PUBLIC}),
        category="not-a-real-category",
    )
    assert "category" in sql
    assert "'not-a-real-category'" in sql


@pytest.mark.asyncio
async def test_list_filtered_sql_uses_bind_params_not_fstring() -> None:
    """Anti-SQL-injection guard: компилятор без literal_binds выдаёт `?`/`:p`,
    не литерал — это значит ORM использует bind params.
    """
    captured: dict[str, Any] = {}

    async def _capture(stmt: Any) -> Any:
        captured["stmt"] = stmt
        scalars = MagicMock()
        scalars.all.return_value = []
        result = MagicMock()
        result.scalars.return_value = scalars
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    repo = ArticleRepository(session)
    await repo.list_filtered(
        frozenset({AccessLevel.PUBLIC}),
        category="'); DROP TABLE articles; --",
    )
    # Без literal_binds — SQL содержит placeholder (`?` или `:name_1`).
    sql_with_binds = str(captured["stmt"].compile())
    assert "DROP TABLE" not in sql_with_binds
    # Параметризованное значение появляется только при literal_binds=True.
    sql_with_literals = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    # При literal_binds — литерал в SQL экранирован одинарными кавычками.
    assert "DROP TABLE" in sql_with_literals  # ровно как escaped string literal


@pytest.mark.asyncio
@pytest.mark.security
async def test_list_filtered_sql_cursor_predicate_is_row_value_not_and() -> None:
    """Keyset row-value `(updated_at, id) < (:u, :i)` — НЕ `updated_at < :u AND id < :i`.

    Второе эквивалентно «или updated_at меньше, или updated_at равен И id меньше»,
    что разваливает keyset при равенстве по `updated_at`. Тест ловит регрессию
    `tuple_()` → split into AND.
    """
    cursor_ts = datetime(2026, 5, 12, 10, 30, 0, tzinfo=UTC)
    cursor_id = uuid4()
    sql = await _capture_list_filtered_sql(
        access_levels=frozenset({AccessLevel.PUBLIC}),
        cursor=(cursor_ts, cursor_id),
    )
    # Row-value comparison оставляет parenthesized tuple на обеих сторонах.
    # SQLAlchemy формат: `(articles.updated_at, articles.id) < (..., ...)`.
    assert (
        "updated_at, articles.id) <" in sql or "(updated_at, id) <" in sql
    ), f"SQL не содержит row-value comparison: {sql}"
    # Не должно быть split на два отдельных AND-предиката:
    assert sql.count("updated_at <") <= 1


@pytest.mark.asyncio
async def test_list_filtered_no_cursor_no_predicate() -> None:
    sql = await _capture_list_filtered_sql(
        access_levels=frozenset({AccessLevel.PUBLIC}),
    )
    assert "<" not in sql.split("ORDER BY")[0].split("LIMIT")[0].replace(
        "ix_", ""
    )  # никаких неравенств в WHERE


@pytest.mark.asyncio
@pytest.mark.security
async def test_list_filtered_empty_access_levels_returns_empty(
    fake_article: Article,
) -> None:
    """Пустой frozenset → IN ([]) — 0 строк. Не падаем, не утекаем."""
    session = _build_session_returning_rows([])
    repo = ArticleRepository(session)
    rows, has_more = await repo.list_filtered(frozenset(), limit=20)
    assert rows == []
    assert has_more is False


# ============================================================
# create tests
# ============================================================


def _valid_input() -> Any:
    from src.api.articles.schemas import ArticleInput

    return ArticleInput(
        slug="new-article",
        title="Тайтл",
        body_markdown="# Body",
        category="guide",
        audience="tenant",
        access_level=AccessLevel.PUBLIC,
    )


@pytest.mark.asyncio
async def test_create_inserts_article_and_returns_with_fields() -> None:
    """Happy path: add → flush → commit → refresh → возврат Article."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock(return_value=None)
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    session.rollback = AsyncMock(return_value=None)

    repo = ArticleRepository(session)
    result = await repo.create(_valid_input())
    assert result.slug == "new-article"
    assert result.access_level == "PUBLIC"  # StrEnum → str для DB
    session.add.assert_called_once()
    session.flush.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(result)


@pytest.mark.asyncio
async def test_create_slug_conflict_raises_409() -> None:
    """IntegrityError с `uq_articles_slug` → SlugConflictError(409)."""
    from src.api.articles.repository import SlugConflictError

    session = MagicMock()
    session.add = MagicMock()
    # `orig` exception text имитирует asyncpg unique violation message.
    orig = Exception("duplicate key value violates unique constraint 'uq_articles_slug'")
    session.flush = AsyncMock(side_effect=IntegrityError("INSERT...", {}, orig))
    session.commit = AsyncMock(return_value=None)
    session.rollback = AsyncMock(return_value=None)

    repo = ArticleRepository(session)
    with pytest.raises(SlugConflictError) as exc:
        await repo.create(_valid_input())
    assert exc.value.status_code == 409
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_returns_article_when_writer_can_see_it(
    fake_article: Article,
) -> None:
    """Happy path: writer видит статью (access_level matches) → обновляет."""
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = fake_article
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)

    repo = ArticleRepository(session)
    payload = _valid_input()
    # Изменяем visibility и status в payload, чтобы дельта была видна.
    payload.access_level = AccessLevel.LOGGED  # was PUBLIC
    payload.status = "ARCHIVED"  # was PUBLISHED

    out = await repo.update(
        "kak-podpisat-dogovor",
        payload,
        frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED}),
    )
    assert out is not None
    article, old_al, old_st = out
    assert article is fake_article
    assert old_al == "PUBLIC"
    assert old_st == "PUBLISHED"
    # In-place mutation проверим.
    assert article.access_level == "LOGGED"
    assert article.status == "ARCHIVED"
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_returns_none_when_article_not_found() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock(return_value=None)

    repo = ArticleRepository(session)
    out = await repo.update("nonexistent", _valid_input(), frozenset({AccessLevel.PUBLIC}))
    assert out is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.security
async def test_update_returns_none_when_scope_cannot_see() -> None:
    """ADR-0003 source-side: scope-out-of-reach неотличимо от nonexistent (404 mask)."""
    session = MagicMock()
    result = MagicMock()
    # Имитируем: SQL отфильтровал статью (access_level не в нашем наборе).
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock(return_value=None)

    repo = ArticleRepository(session)
    out = await repo.update("hr-article", _valid_input(), frozenset({AccessLevel.PUBLIC}))
    assert out is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.security
async def test_update_sql_does_not_filter_status_published() -> None:
    """Writer должен видеть DRAFT/ARCHIVED — НЕТ статусного фильтра."""
    captured: dict[str, Any] = {}

    async def _capture(stmt: Any) -> Any:
        captured["stmt"] = stmt
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    repo = ArticleRepository(session)
    await repo.update("some-slug", _valid_input(), frozenset({AccessLevel.PUBLIC}))
    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    # access_level filter обязателен.
    assert "access_level IN" in sql
    assert "slug" in sql
    # status='PUBLISHED' filter — ОТСУТСТВУЕТ (writer видит drafts).
    assert "'PUBLISHED'" not in sql


@pytest.mark.asyncio
@pytest.mark.security
@pytest.mark.parametrize(
    "scope",
    [
        Scope.STAFF_SUPPORT,
        Scope.STAFF_LEGAL,
        Scope.STAFF_HR,
        Scope.STAFF_ADMIN,
    ],
)
async def test_update_sql_includes_correct_access_levels_per_scope(
    scope: Scope,
) -> None:
    """ADR-0003 critical: SQL содержит ровно те access_levels, что выдал
    `compute_access_levels` для каждого write-capable Scope.

    Особо: staff_admin БЕЗ HR_RESTRICTED — не должен видеть HR статьи
    для update (404 mask). staff_hr ИМЕЕТ HR_RESTRICTED.
    """
    role_map = {
        Scope.STAFF_SUPPORT: ["staff_support"],
        Scope.STAFF_LEGAL: ["staff_legal"],
        Scope.STAFF_HR: ["staff_hr"],
        Scope.STAFF_ADMIN: ["staff_admin"],
    }
    levels = compute_access_levels(role_map[scope])
    captured: dict[str, Any] = {}

    async def _capture(stmt: Any) -> Any:
        captured["stmt"] = stmt
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    repo = ArticleRepository(session)
    await repo.update("any-slug", _valid_input(), levels)
    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))

    assert "access_level IN" in sql
    for lvl in levels:
        assert f"'{lvl.value}'" in sql

    # Forbidden levels не должны попасть в IN.
    all_levels: set[AccessLevel] = set(AccessLevel.__members__.values())
    for forbidden_lvl in all_levels - levels:
        assert f"'{forbidden_lvl.value}'" not in sql, (
            f"Scope={scope.value}: access_level={forbidden_lvl.value} утёк в SQL "
            "(ADR-0003 regression)"
        )


@pytest.mark.asyncio
async def test_create_unknown_integrity_error_propagated() -> None:
    """IntegrityError, не slug-conflict (например CHECK violation) → 500/пробрасывается."""
    session = MagicMock()
    session.add = MagicMock()
    orig = Exception("violates check constraint 'ck_articles_audience'")
    session.flush = AsyncMock(side_effect=IntegrityError("INSERT...", {}, orig))
    session.commit = AsyncMock(return_value=None)
    session.rollback = AsyncMock(return_value=None)

    repo = ArticleRepository(session)
    with pytest.raises(IntegrityError):
        await repo.create(_valid_input())
    session.rollback.assert_awaited_once()


# Импорт IntegrityError для тестов выше — добавим в начале файла.
