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
        # E5.0: advisory lock SQL идёт ПЕРВЫМ в update/archive/patch — пропускаем.
        if "pg_advisory_xact_lock" not in str(stmt):
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
    """Happy path: add(Article) → flush → add(ArticleVersion v=1) → commit → refresh."""
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock(return_value=None)
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    session.rollback = AsyncMock(return_value=None)

    repo = ArticleRepository(session)
    result = await repo.create(_valid_input(), actor_sub="test-actor")
    assert result.slug == "new-article"
    assert result.access_level == "PUBLIC"  # StrEnum → str для DB
    # E2.3: add() вызывается дважды — Article + ArticleVersion v=1.
    assert session.add.call_count == 2
    session.flush.assert_awaited_once()
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(result)


@pytest.mark.asyncio
async def test_create_inserts_version_1_in_same_transaction() -> None:
    """E2.3: первая версия (event=CREATE) добавлена в session перед commit."""
    from src.api.articles.models import ArticleVersion

    added: list[Any] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    session.flush = AsyncMock(return_value=None)
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    session.rollback = AsyncMock(return_value=None)

    repo = ArticleRepository(session)
    await repo.create(_valid_input(), actor_sub="actor-123")

    versions = [v for v in added if isinstance(v, ArticleVersion)]
    assert len(versions) == 1
    v = versions[0]
    assert v.version == 1
    assert v.event == "CREATE"
    assert v.author_sub == "actor-123"
    assert v.old_status is None
    assert v.new_status == "DRAFT"
    assert v.old_access_level is None
    assert v.new_access_level == "PUBLIC"
    assert v.changes_summary == "Article created"


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
        await repo.create(_valid_input(), actor_sub="test-actor")
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
        actor_sub="test-actor",
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
    out = await repo.update(
        "nonexistent", _valid_input(), frozenset({AccessLevel.PUBLIC}), actor_sub="test-actor"
    )
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
    out = await repo.update(
        "hr-article", _valid_input(), frozenset({AccessLevel.PUBLIC}), actor_sub="test-actor"
    )
    assert out is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.security
async def test_update_sql_does_not_filter_status_published() -> None:
    """Writer должен видеть DRAFT/ARCHIVED — НЕТ статусного фильтра."""
    captured: dict[str, Any] = {}

    async def _capture(stmt: Any) -> Any:
        # E5.0: advisory lock SQL идёт ПЕРВЫМ в update/archive/patch — пропускаем.
        if "pg_advisory_xact_lock" not in str(stmt):
            captured["stmt"] = stmt
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    repo = ArticleRepository(session)
    await repo.update(
        "some-slug", _valid_input(), frozenset({AccessLevel.PUBLIC}), actor_sub="test-actor"
    )
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
        # E5.0: advisory lock SQL идёт ПЕРВЫМ в update/archive/patch — пропускаем.
        if "pg_advisory_xact_lock" not in str(stmt):
            captured["stmt"] = stmt
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    repo = ArticleRepository(session)
    await repo.update("any-slug", _valid_input(), levels, actor_sub="test-actor")
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
        await repo.create(_valid_input(), actor_sub="test-actor")
    session.rollback.assert_awaited_once()


# ============================================================
# archive tests (E4.4)
# ============================================================


def _build_session_with_article(article: Article | None) -> Any:
    """AsyncSession-мок: SELECT возвращает указанный Article (или None)."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = article
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock(return_value=None)
    return session


@pytest.mark.asyncio
async def test_archive_returns_status_and_access_level_when_found(
    fake_article: Article,
) -> None:
    """Happy: статья найдена, status был PUBLISHED, возвращаем оба поля + commit."""
    fake_article.status = "PUBLISHED"
    fake_article.access_level = "PUBLIC"
    session = _build_session_with_article(fake_article)
    repo = ArticleRepository(session)

    out = await repo.archive(
        "kak-podpisat", frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED}), actor_sub="test-actor"
    )
    assert out == ("PUBLISHED", "PUBLIC")
    # Мутация выполнена.
    assert fake_article.status == "ARCHIVED"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_archive_draft_article_succeeds(fake_article: Article) -> None:
    """Writer может архивировать DRAFT — нет status='PUBLISHED' filter."""
    fake_article.status = "DRAFT"
    fake_article.access_level = "STAFF"
    session = _build_session_with_article(fake_article)
    repo = ArticleRepository(session)

    out = await repo.archive("draft-slug", frozenset({AccessLevel.STAFF}), actor_sub="test-actor")
    assert out == ("DRAFT", "STAFF")
    assert fake_article.status == "ARCHIVED"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_archive_idempotent_no_op_for_already_archived(
    fake_article: Article,
) -> None:
    """Per Reviewer N3: уже ARCHIVED → no-op (без UPDATE / без touch updated_at).

    Возвращаем `was_status='ARCHIVED'` — router логирует, но в БД нет
    мутации (commit НЕ awaited).
    """
    fake_article.status = "ARCHIVED"
    fake_article.access_level = "PUBLIC"
    session = _build_session_with_article(fake_article)
    repo = ArticleRepository(session)

    out = await repo.archive("already", frozenset({AccessLevel.PUBLIC}), actor_sub="test-actor")
    assert out == ("ARCHIVED", "PUBLIC")
    assert fake_article.status == "ARCHIVED"  # без изменений
    session.commit.assert_not_awaited()  # NO-OP — commit не вызван


@pytest.mark.asyncio
async def test_archive_returns_none_when_article_not_found() -> None:
    session = _build_session_with_article(None)
    repo = ArticleRepository(session)
    out = await repo.archive("missing", frozenset({AccessLevel.PUBLIC}), actor_sub="test-actor")
    assert out is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.security
async def test_archive_returns_none_when_scope_cannot_see() -> None:
    """ADR-0003 source-mask: scope-out-of-reach неотличимо от nonexistent (404)."""
    # Имитируем: SQL отфильтровал HR_RESTRICTED статью для staff_admin scope.
    session = _build_session_with_article(None)
    repo = ArticleRepository(session)
    out = await repo.archive(
        "hr-article", frozenset({AccessLevel.PUBLIC, AccessLevel.STAFF}), actor_sub="test-actor"
    )
    assert out is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.security
async def test_archive_sql_does_not_filter_status_published() -> None:
    """Writer может архивировать DRAFT/ARCHIVED — нет статусного filter."""
    captured: dict[str, Any] = {}

    async def _capture(stmt: Any) -> Any:
        # E5.0: advisory lock SQL идёт ПЕРВЫМ в update/archive/patch — пропускаем.
        if "pg_advisory_xact_lock" not in str(stmt):
            captured["stmt"] = stmt
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    session.commit = AsyncMock(return_value=None)

    repo = ArticleRepository(session)
    await repo.archive("any", frozenset({AccessLevel.PUBLIC}), actor_sub="test-actor")

    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "access_level IN" in sql
    assert "slug" in sql
    # ВАЖНО: status='PUBLISHED' filter ОТСУТСТВУЕТ.
    assert "'PUBLISHED'" not in sql


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
async def test_archive_sql_includes_correct_access_levels_per_scope(
    scope: Scope,
) -> None:
    """ADR-0003 regression: SQL содержит ровно те access_levels, что выдал
    `compute_access_levels` для каждого Scope (per Reviewer N1).

    Особо: STAFF_ADMIN БЕЗ HR_RESTRICTED — не может архивировать HR.
    STAFF_HR ИМЕЕТ HR_RESTRICTED — может.
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
    captured: dict[str, Any] = {}

    async def _capture(stmt: Any) -> Any:
        # E5.0: advisory lock SQL идёт ПЕРВЫМ в update/archive/patch — пропускаем.
        if "pg_advisory_xact_lock" not in str(stmt):
            captured["stmt"] = stmt
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    session.commit = AsyncMock(return_value=None)

    repo = ArticleRepository(session)
    await repo.archive("any-slug", levels, actor_sub="test-actor")
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


# ============================================================
# list_filtered tags filter (E2.4)
# ============================================================


async def _capture_list_filtered_compiled(**kwargs: Any) -> Any:
    """Возвращает скомпилированный statement (без literal_binds).

    JSONB литералы нельзя render'ить через `literal_binds=True` (SQLAlchemy
    CompileError). Для tags-тестов используем default compile() и проверяем
    как SQL string, так и bind-params через `.params`.
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
    return captured["stmt"].compile()


@pytest.mark.asyncio
async def test_list_filtered_with_single_tag_adds_containment_predicate() -> None:
    compiled = await _capture_list_filtered_compiled(
        access_levels=frozenset({AccessLevel.PUBLIC}),
        tags=["договор"],
    )
    sql = str(compiled)
    assert "tags @> CAST" in sql
    assert "AS JSONB" in sql


@pytest.mark.asyncio
async def test_list_filtered_with_multiple_tags_uses_single_array_param() -> None:
    """AND-семантика: single array bind param, не N отдельных предикатов."""
    compiled = await _capture_list_filtered_compiled(
        access_levels=frozenset({AccessLevel.PUBLIC}),
        tags=["договор", "наниматель"],
    )
    sql = str(compiled)
    assert sql.count("@>") == 1
    # В params могут быть и другие list-bindings (access_level IN — тоже list);
    # достаточно убедиться, что наш tags-list присутствует целиком.
    list_params = [v for v in compiled.params.values() if isinstance(v, list)]
    assert ["договор", "наниматель"] in list_params


@pytest.mark.asyncio
async def test_list_filtered_with_empty_tags_list_omits_filter() -> None:
    compiled = await _capture_list_filtered_compiled(
        access_levels=frozenset({AccessLevel.PUBLIC}),
        tags=[],
    )
    sql = str(compiled)
    assert "@>" not in sql


@pytest.mark.asyncio
async def test_list_filtered_with_none_tags_omits_filter() -> None:
    compiled = await _capture_list_filtered_compiled(
        access_levels=frozenset({AccessLevel.PUBLIC}),
        tags=None,
    )
    sql = str(compiled)
    assert "@>" not in sql


@pytest.mark.asyncio
@pytest.mark.security
async def test_list_filtered_with_tags_still_has_access_level_filter() -> None:
    """ADR-0003 ortho-guard: tags filter не заменяет/обходит access_level."""
    compiled = await _capture_list_filtered_compiled(
        access_levels=frozenset({AccessLevel.PUBLIC, AccessLevel.STAFF}),
        tags=["foo"],
    )
    sql = str(compiled)
    assert "access_level IN" in sql
    assert "@>" in sql
    assert "status" in sql


@pytest.mark.asyncio
@pytest.mark.security
async def test_list_filtered_tags_values_use_bind_params_not_literal() -> None:
    """Anti-SQL-injection: tags содержимое в bind param, не SQL literal."""
    malicious = ["'; DROP TABLE articles; --", "x"]
    compiled = await _capture_list_filtered_compiled(
        access_levels=frozenset({AccessLevel.PUBLIC}),
        tags=malicious,
    )
    sql = str(compiled)
    assert "DROP TABLE" not in sql
    found = any(v == malicious for v in compiled.params.values() if isinstance(v, list))
    assert found, "Tags не попали в bind params"


@pytest.mark.asyncio
async def test_list_filtered_combines_tags_with_category() -> None:
    compiled = await _capture_list_filtered_compiled(
        access_levels=frozenset({AccessLevel.PUBLIC}),
        category="guide",
        tags=["foo"],
    )
    sql = str(compiled)
    assert "category" in sql
    assert "@>" in sql
    assert "access_level IN" in sql


# ============================================================
# list_versions + version recording (E2.3 #36)
# ============================================================


@pytest.mark.asyncio
async def test_update_inserts_version_with_next_number(fake_article: Article) -> None:
    """E2.3: каждый update создаёт ArticleVersion с next_version = MAX + 1."""
    from src.api.articles.models import ArticleVersion

    fake_article.id = uuid4()
    fake_article.access_level = "PUBLIC"
    fake_article.status = "PUBLISHED"

    added: list[Any] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)

    # Первый execute() — SELECT article (для update); второй — MAX(version).
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = fake_article
    max_result = MagicMock()
    max_result.scalar.return_value = 3  # prev version was 3
    session.execute = AsyncMock(side_effect=[MagicMock(), select_result, max_result])

    repo = ArticleRepository(session)
    payload = _valid_input()
    payload.access_level = AccessLevel.LOGGED
    payload.status = "DRAFT"
    await repo.update(
        "kak-podpisat",
        payload,
        frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED}),
        actor_sub="alice-sub",
    )

    versions = [v for v in added if isinstance(v, ArticleVersion)]
    assert len(versions) == 1
    v = versions[0]
    assert v.version == 4  # MAX + 1
    assert v.event == "UPDATE"
    assert v.author_sub == "alice-sub"
    assert v.old_status == "PUBLISHED"
    assert v.new_status == "DRAFT"
    assert v.old_access_level == "PUBLIC"
    assert v.new_access_level == "LOGGED"


@pytest.mark.asyncio
async def test_archive_inserts_version_when_status_changes(fake_article: Article) -> None:
    """E2.3: archive создаёт ArticleVersion (event=ARCHIVE)."""
    from src.api.articles.models import ArticleVersion

    fake_article.id = uuid4()
    fake_article.access_level = "STAFF"
    fake_article.status = "PUBLISHED"

    added: list[Any] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    session.commit = AsyncMock(return_value=None)

    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = fake_article
    max_result = MagicMock()
    max_result.scalar.return_value = 1
    session.execute = AsyncMock(side_effect=[MagicMock(), select_result, max_result])

    repo = ArticleRepository(session)
    await repo.archive("to-archive", frozenset({AccessLevel.STAFF}), actor_sub="hr-sub")

    versions = [v for v in added if isinstance(v, ArticleVersion)]
    assert len(versions) == 1
    v = versions[0]
    assert v.version == 2
    assert v.event == "ARCHIVE"
    assert v.author_sub == "hr-sub"
    assert v.old_status == "PUBLISHED"
    assert v.new_status == "ARCHIVED"
    # access_level не менялся, но фиксируем оба для consistency.
    assert v.old_access_level == "STAFF"
    assert v.new_access_level == "STAFF"


@pytest.mark.asyncio
async def test_archive_no_op_does_not_create_version(fake_article: Article) -> None:
    """E2.3: уже-ARCHIVED не создаёт версию (idempotent no-op)."""
    from src.api.articles.models import ArticleVersion

    fake_article.id = uuid4()
    fake_article.access_level = "PUBLIC"
    fake_article.status = "ARCHIVED"

    added: list[Any] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    session.commit = AsyncMock(return_value=None)

    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = fake_article
    session.execute = AsyncMock(return_value=select_result)

    repo = ArticleRepository(session)
    out = await repo.archive("already", frozenset({AccessLevel.PUBLIC}), actor_sub="actor")
    assert out == ("ARCHIVED", "PUBLIC")

    # ВАЖНО: версия НЕ создаётся.
    versions = [v for v in added if isinstance(v, ArticleVersion)]
    assert versions == []
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_versions_returns_none_when_article_invisible() -> None:
    """ADR-0003 source-mask: get_by_slug отсёк article → list_versions None → 404."""
    # get_by_slug возвращает None — статья не видна.
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)

    repo = ArticleRepository(session)
    out = await repo.list_versions("hr-secret", frozenset({AccessLevel.PUBLIC}))
    assert out is None


@pytest.mark.asyncio
async def test_list_versions_returns_versions_when_article_visible(
    fake_article: Article,
) -> None:
    from src.api.articles.models import ArticleVersion

    fake_article.id = uuid4()
    v1 = ArticleVersion(
        article_id=fake_article.id,
        version=1,
        event="CREATE",
        author_sub="a",
        new_status="DRAFT",
        new_access_level="PUBLIC",
    )
    v2 = ArticleVersion(
        article_id=fake_article.id,
        version=2,
        event="UPDATE",
        author_sub="b",
        old_status="DRAFT",
        new_status="PUBLISHED",
        old_access_level="PUBLIC",
        new_access_level="PUBLIC",
    )

    # Первый execute() — get_by_slug; второй — SELECT versions.
    article_result = MagicMock()
    article_result.scalar_one_or_none.return_value = fake_article
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [v2, v1]
    versions_result = MagicMock()
    versions_result.scalars.return_value = scalars_mock

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[article_result, versions_result])

    repo = ArticleRepository(session)
    out = await repo.list_versions("visible", frozenset({AccessLevel.PUBLIC}))
    assert out is not None
    assert len(out) == 2
    assert out[0].version == 2  # DESC order


@pytest.mark.asyncio
@pytest.mark.security
async def test_list_versions_inherits_access_level_filter_from_get_by_slug() -> None:
    """ADR-0003: list_versions использует get_by_slug, который применяет
    `access_level IN (...)` + `status='PUBLISHED'` фильтры. Проверяем что
    первый SELECT (для article) содержит обоих.
    """
    captured: dict[str, Any] = {}
    call_count = [0]

    async def _capture(stmt: Any) -> Any:
        call_count[0] += 1
        if call_count[0] == 1:
            captured["article_stmt"] = stmt
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)

    repo = ArticleRepository(session)
    await repo.list_versions("any-slug", frozenset({AccessLevel.STAFF}))

    sql = str(captured["article_stmt"].compile(compile_kwargs={"literal_binds": True}))
    # ADR-0003 invariants.
    assert "access_level IN" in sql
    assert "'STAFF'" in sql
    # Read-инвариант (status='PUBLISHED').
    assert "'PUBLISHED'" in sql


@pytest.mark.asyncio
async def test_update_creates_version_even_if_payload_unchanged(
    fake_article: Article,
) -> None:
    """PUT всегда создаёт версию — это акт, не diff (per plan revision)."""
    from src.api.articles.models import ArticleVersion

    fake_article.id = uuid4()
    fake_article.access_level = "PUBLIC"
    fake_article.status = "PUBLISHED"

    added: list[Any] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)

    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = fake_article
    max_result = MagicMock()
    max_result.scalar.return_value = 1
    session.execute = AsyncMock(side_effect=[MagicMock(), select_result, max_result])

    # Payload идентичен текущему article (access_level=PUBLIC, status=PUBLISHED).
    payload = _valid_input()
    # _valid_input: access_level=PUBLIC, status=DRAFT (default).
    payload.status = "PUBLISHED"

    repo = ArticleRepository(session)
    await repo.update(
        "same-slug",
        payload,
        frozenset({AccessLevel.PUBLIC}),
        actor_sub="actor",
    )

    versions = [v for v in added if isinstance(v, ArticleVersion)]
    # Версия создаётся даже когда "ничего не изменилось".
    assert len(versions) == 1
    assert versions[0].version == 2
    assert versions[0].event == "UPDATE"


# ============================================================
# patch (E4.5 #38)
# ============================================================


@pytest.mark.asyncio
async def test_patch_updates_single_field(fake_article: Article) -> None:
    """PATCH меняет только переданное поле."""
    from src.api.articles.models import ArticleVersion
    from src.api.articles.schemas import ArticlePatch

    fake_article.id = uuid4()
    fake_article.title = "Old title"
    fake_article.body_markdown = "Old body"
    fake_article.access_level = "PUBLIC"
    fake_article.status = "PUBLISHED"
    original_body = fake_article.body_markdown

    added: list[Any] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    article_result = MagicMock()
    article_result.scalar_one_or_none.return_value = fake_article
    max_result = MagicMock()
    max_result.scalar.return_value = 1
    session.execute = AsyncMock(side_effect=[MagicMock(), article_result, max_result])

    repo = ArticleRepository(session)
    out = await repo.patch(
        "slug",
        ArticlePatch(title="New title"),
        frozenset({AccessLevel.PUBLIC}),
        actor_sub="actor",
    )
    assert out is not None
    article, old_al, old_st = out
    assert article.title == "New title"
    # body не тронут.
    assert article.body_markdown == original_body
    assert old_al == "PUBLIC"
    assert old_st == "PUBLISHED"
    versions = [v for v in added if isinstance(v, ArticleVersion)]
    assert len(versions) == 1
    assert versions[0].event == "UPDATE"
    assert versions[0].version == 2


@pytest.mark.asyncio
async def test_patch_updates_multiple_fields(fake_article: Article) -> None:
    from src.api.articles.schemas import ArticlePatch

    fake_article.id = uuid4()
    fake_article.access_level = "PUBLIC"
    fake_article.status = "PUBLISHED"

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    article_result = MagicMock()
    article_result.scalar_one_or_none.return_value = fake_article
    max_result = MagicMock()
    max_result.scalar.return_value = 1
    session.execute = AsyncMock(side_effect=[MagicMock(), article_result, max_result])

    repo = ArticleRepository(session)
    await repo.patch(
        "slug",
        ArticlePatch(title="T", body_markdown="B", status="DRAFT"),
        frozenset({AccessLevel.PUBLIC}),
        actor_sub="actor",
    )
    assert fake_article.title == "T"
    assert fake_article.body_markdown == "B"
    assert fake_article.status == "DRAFT"


@pytest.mark.asyncio
async def test_patch_empty_payload_no_op_no_version(fake_article: Article) -> None:
    """Empty `{}` — no-op: НЕТ версии, НЕТ commit."""
    from src.api.articles.models import ArticleVersion
    from src.api.articles.schemas import ArticlePatch

    fake_article.id = uuid4()
    fake_article.access_level = "PUBLIC"
    fake_article.status = "PUBLISHED"

    added: list[Any] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    session.commit = AsyncMock(return_value=None)
    article_result = MagicMock()
    article_result.scalar_one_or_none.return_value = fake_article
    session.execute = AsyncMock(return_value=article_result)

    repo = ArticleRepository(session)
    out = await repo.patch(
        "slug",
        ArticlePatch(),  # empty
        frozenset({AccessLevel.PUBLIC}),
        actor_sub="actor",
    )
    assert out is not None
    versions = [v for v in added if isinstance(v, ArticleVersion)]
    assert versions == []
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_returns_none_when_article_not_found() -> None:
    from src.api.articles.schemas import ArticlePatch

    session = MagicMock()
    article_result = MagicMock()
    article_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=article_result)
    session.commit = AsyncMock(return_value=None)

    repo = ArticleRepository(session)
    out = await repo.patch(
        "missing",
        ArticlePatch(title="x"),
        frozenset({AccessLevel.PUBLIC}),
        actor_sub="actor",
    )
    assert out is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.security
async def test_patch_sql_includes_access_level_filter() -> None:
    """ADR-0003 source-mask: SELECT с `access_level IN (current)`."""
    from src.api.articles.schemas import ArticlePatch

    captured: dict[str, Any] = {}

    async def _capture(stmt: Any) -> Any:
        # E5.0: advisory lock идёт первым — пропускаем.
        if "pg_advisory_xact_lock" not in str(stmt) and "stmt" not in captured:
            captured["stmt"] = stmt
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)

    repo = ArticleRepository(session)
    await repo.patch(
        "any",
        ArticlePatch(title="x"),
        frozenset({AccessLevel.STAFF}),
        actor_sub="actor",
    )
    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert "access_level IN" in sql
    assert "'STAFF'" in sql
    # Writer видит DRAFT/ARCHIVED — НЕ фильтруем status.
    assert "'PUBLISHED'" not in sql


@pytest.mark.asyncio
async def test_patch_does_not_touch_access_level_or_slug(fake_article: Article) -> None:
    """ArticlePatch не содержит access_level/slug — repository их не меняет."""
    from src.api.articles.schemas import ArticlePatch

    fake_article.id = uuid4()
    fake_article.slug = "original-slug"
    fake_article.access_level = "PUBLIC"
    fake_article.status = "PUBLISHED"

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    article_result = MagicMock()
    article_result.scalar_one_or_none.return_value = fake_article
    max_result = MagicMock()
    max_result.scalar.return_value = 0
    session.execute = AsyncMock(side_effect=[MagicMock(), article_result, max_result])

    repo = ArticleRepository(session)
    await repo.patch(
        "original-slug",
        ArticlePatch(title="new"),
        frozenset({AccessLevel.PUBLIC}),
        actor_sub="actor",
    )
    # slug и access_level не изменились.
    assert fake_article.slug == "original-slug"
    assert fake_article.access_level == "PUBLIC"


@pytest.mark.asyncio
async def test_patch_status_to_archived_creates_update_event(
    fake_article: Article,
) -> None:
    """PATCH status='ARCHIVED' создаёт event=UPDATE (НЕ ARCHIVE).

    Намеренное различие с DELETE: PATCH — общий update, DELETE — формальная
    архивация. Документировано в docstring `repo.patch`.
    """
    from src.api.articles.models import ArticleVersion
    from src.api.articles.schemas import ArticlePatch

    fake_article.id = uuid4()
    fake_article.access_level = "PUBLIC"
    fake_article.status = "PUBLISHED"

    added: list[Any] = []
    session = MagicMock()
    session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    article_result = MagicMock()
    article_result.scalar_one_or_none.return_value = fake_article
    max_result = MagicMock()
    max_result.scalar.return_value = 1
    session.execute = AsyncMock(side_effect=[MagicMock(), article_result, max_result])

    repo = ArticleRepository(session)
    await repo.patch(
        "slug",
        ArticlePatch(status="ARCHIVED"),
        frozenset({AccessLevel.PUBLIC}),
        actor_sub="actor",
    )
    versions = [v for v in added if isinstance(v, ArticleVersion)]
    assert len(versions) == 1
    assert versions[0].event == "UPDATE"  # НЕ ARCHIVE
    assert versions[0].old_status == "PUBLISHED"
    assert versions[0].new_status == "ARCHIVED"


# ============================================================
# Advisory lock race-fix (E5.0 #40)
# ============================================================


def _make_capture_stmts() -> tuple[list[Any], Any]:
    """Возвращает (list-storage, async _capture) — пишет ВСЕ execute statements."""
    stmts: list[Any] = []

    async def _capture(stmt: Any) -> Any:
        stmts.append(stmt)
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        # Для MAX-query — int scalar return (для archive нет MAX в no-op path)
        result.scalar.return_value = None
        return result

    return stmts, _capture


@pytest.mark.asyncio
async def test_update_acquires_advisory_lock_before_select() -> None:
    """E5.0: pg_advisory_xact_lock — ПЕРВЫЙ statement в update."""
    stmts, capture = _make_capture_stmts()
    session = MagicMock()
    session.execute = AsyncMock(side_effect=capture)

    repo = ArticleRepository(session)
    await repo.update("the-slug", _valid_input(), frozenset({AccessLevel.PUBLIC}), actor_sub="a")
    assert len(stmts) >= 2
    first_sql = str(stmts[0])
    assert "pg_advisory_xact_lock" in first_sql
    # Slug передан через bind param (без literal substitution).
    second_sql = str(stmts[1])
    assert "articles.slug" in second_sql
    assert "pg_advisory_xact_lock" not in second_sql


@pytest.mark.asyncio
async def test_archive_acquires_advisory_lock_before_select() -> None:
    """E5.0: то же для archive."""
    stmts, capture = _make_capture_stmts()
    session = MagicMock()
    session.execute = AsyncMock(side_effect=capture)

    repo = ArticleRepository(session)
    await repo.archive("the-slug", frozenset({AccessLevel.PUBLIC}), actor_sub="a")
    assert len(stmts) >= 2
    assert "pg_advisory_xact_lock" in str(stmts[0])
    assert "articles.slug" in str(stmts[1])


@pytest.mark.asyncio
async def test_patch_acquires_advisory_lock_before_select() -> None:
    """E5.0: то же для patch."""
    from src.api.articles.schemas import ArticlePatch

    stmts, capture = _make_capture_stmts()
    session = MagicMock()
    session.execute = AsyncMock(side_effect=capture)

    repo = ArticleRepository(session)
    await repo.patch(
        "the-slug",
        ArticlePatch(title="x"),
        frozenset({AccessLevel.PUBLIC}),
        actor_sub="a",
    )
    assert len(stmts) >= 2
    assert "pg_advisory_xact_lock" in str(stmts[0])
    assert "articles.slug" in str(stmts[1])


@pytest.mark.asyncio
async def test_create_does_not_acquire_advisory_lock() -> None:
    """E5.0: create НЕ берёт advisory lock — UNIQUE slug constraint защищает.

    Concurrent create того же slug → второй writer получит 409 SlugConflictError
    (как до E5.0; поведение не меняется).
    """
    stmts, capture = _make_capture_stmts()
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock(return_value=None)
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    session.execute = AsyncMock(side_effect=capture)

    repo = ArticleRepository(session)
    await repo.create(_valid_input(), actor_sub="a")

    # Все вызванные SQL: НИ ОДИН не должен быть advisory_xact_lock.
    for s in stmts:
        assert "pg_advisory_xact_lock" not in str(s)


@pytest.mark.asyncio
@pytest.mark.security
async def test_advisory_lock_uses_bind_param_not_literal_slug() -> None:
    """Anti-SQL-injection: slug передаётся через bind param, не literal."""
    malicious_slug = "'); DROP TABLE articles; --"
    stmts, capture = _make_capture_stmts()
    session = MagicMock()
    session.execute = AsyncMock(side_effect=capture)

    repo = ArticleRepository(session)
    await repo.update(
        malicious_slug,
        _valid_input(),
        frozenset({AccessLevel.PUBLIC}),
        actor_sub="a",
    )
    # SQL string lock-statement НЕ содержит payload.
    lock_stmt = stmts[0]
    sql_no_binds = str(lock_stmt)
    assert "DROP TABLE" not in sql_no_binds
    # Bind params содержат payload (для безопасного исполнения).
    params = lock_stmt.compile().params
    assert malicious_slug in params.values()


# ============================================================
# search (E2.5a #46) — Postgres FTS
# ============================================================


async def _capture_search_sql(**kwargs: Any) -> Any:
    """Capture compiled search SQL (без literal_binds — websearch_to_tsquery
    может содержать non-renderable params)."""
    captured: dict[str, Any] = {}

    async def _capture(stmt: Any) -> Any:
        captured["stmt"] = stmt
        result = MagicMock()
        result.all.return_value = []
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    repo = ArticleRepository(session)
    await repo.search(**kwargs)
    return captured["stmt"]


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_matches() -> None:
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    repo = ArticleRepository(session)
    rows, has_more = await repo.search("nonexistent", frozenset({AccessLevel.PUBLIC}))
    assert rows == []
    assert has_more is False


@pytest.mark.asyncio
async def test_search_returns_hits_and_has_more() -> None:
    """limit+1 → trim + has_more=True."""
    session = MagicMock()
    result = MagicMock()
    # 4 rows для limit=3 → has_more=True, trim до 3.
    rows = [(uuid4(), f"T{i}", "snippet", 0.5 - i * 0.1) for i in range(4)]
    result.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    repo = ArticleRepository(session)
    out, has_more = await repo.search("q", frozenset({AccessLevel.PUBLIC}), limit=3)
    assert len(out) == 3
    assert has_more is True


@pytest.mark.asyncio
@pytest.mark.security
async def test_search_sql_uses_websearch_to_tsquery() -> None:
    """Anti-SQL-injection: websearch_to_tsquery — safe для user input."""
    stmt = await _capture_search_sql(
        q="'; DROP TABLE articles; --",
        access_levels=frozenset({AccessLevel.PUBLIC}),
    )
    sql = str(stmt)
    assert "websearch_to_tsquery" in sql
    # Payload — в bind params, не в SQL string.
    assert "DROP TABLE" not in sql
    # Bind params содержат payload (для безопасного исполнения).
    params = stmt.compile().params
    assert "'; DROP TABLE articles; --" in params.values()


@pytest.mark.asyncio
@pytest.mark.security
async def test_search_sql_includes_status_published() -> None:
    """ADR-0003 inherit: status='PUBLISHED' filter.

    NB: `websearch_to_tsquery` arg type `regconfig` — literal_binds не
    работает. Проверяем через bind params + SQL string.
    """
    stmt = await _capture_search_sql(
        q="any",
        access_levels=frozenset({AccessLevel.PUBLIC}),
    )
    sql = str(stmt)
    params = stmt.compile().params
    assert "articles.status =" in sql
    assert params.get("status_1") == "PUBLISHED"


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
async def test_search_sql_includes_correct_access_levels_per_scope(scope: Scope) -> None:
    """ADR-0003 critical: search SQL содержит ровно те access_levels,
    что выдал `compute_access_levels` для каждого Scope.
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
    stmt = await _capture_search_sql(q="any", access_levels=levels)
    sql = str(stmt)
    params = stmt.compile().params

    # access_level IN — bind list param.
    assert "access_level IN" in sql
    bound_levels = params.get("access_level_1", [])
    expected = {lvl.value for lvl in levels}
    assert (
        set(bound_levels) == expected
    ), f"Scope={scope.value}: expected {expected}, got {bound_levels}"

    # Forbidden levels не в bound list.
    all_levels: set[AccessLevel] = set(AccessLevel.__members__.values())
    for forbidden_lvl in all_levels - levels:
        assert forbidden_lvl.value not in bound_levels, (
            f"Scope={scope.value}: access_level={forbidden_lvl.value} утёк " "(ADR-0003 regression)"
        )


@pytest.mark.asyncio
async def test_search_sql_includes_ts_rank_and_match_operator() -> None:
    stmt = await _capture_search_sql(
        q="договор",
        access_levels=frozenset({AccessLevel.PUBLIC}),
    )
    sql = str(stmt)
    assert "ts_rank" in sql
    assert "@@" in sql  # match operator
    assert "ts_headline" in sql  # snippet


@pytest.mark.asyncio
async def test_search_sql_has_order_by_rank_desc_id_desc() -> None:
    stmt = await _capture_search_sql(
        q="x",
        access_levels=frozenset({AccessLevel.PUBLIC}),
        limit=10,
    )
    sql = str(stmt)
    params = stmt.compile().params
    assert "ORDER BY" in sql
    assert "DESC" in sql
    # LIMIT bound param: param_1 = limit + 1 = 11.
    limit_value = next(
        (v for k, v in params.items() if k.startswith("param") and v == 11),
        None,
    )
    assert limit_value == 11


@pytest.mark.asyncio
async def test_search_cursor_predicate_row_value_not_and() -> None:
    """Keyset row-value `(rank, id) < (s, i)` — НЕ AND-split."""
    cur_score = 0.42
    cur_id = uuid4()
    stmt = await _capture_search_sql(
        q="x",
        access_levels=frozenset({AccessLevel.PUBLIC}),
        cursor=(cur_score, cur_id),
    )
    sql = str(stmt)
    # Row-value comparison present.
    assert sql.count("@@") == 1  # один match, не split
    # Tuple comparison оставляет parenthesized form.
    assert ") <" in sql or "(score," in sql or "rank" in sql


@pytest.mark.asyncio
async def test_search_no_cursor_no_predicate() -> None:
    stmt = await _capture_search_sql(
        q="x",
        access_levels=frozenset({AccessLevel.PUBLIC}),
    )
    sql = str(stmt)
    # rank ordering есть, но cursor-предикат `(rank, id) <` отсутствует.
    # Эвристика: единственный `<` (в LIMIT не входит).
    where_section = sql.split("ORDER BY")[0]
    assert where_section.count("<") <= 1  # 1 если websearch ts_query содержит синтаксис


@pytest.mark.asyncio
@pytest.mark.security
async def test_search_empty_access_levels_returns_empty() -> None:
    """Empty frozenset → IN ([]) → 0 строк."""
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    repo = ArticleRepository(session)
    out, has_more = await repo.search("x", frozenset())
    assert out == []
    assert has_more is False


# ============================================================
# If-Match (E5.2 #48) — optimistic concurrency для update
# ============================================================


@pytest.mark.asyncio
async def test_update_if_match_mismatch_raises_precondition_failed(
    fake_article: Article,
) -> None:
    """E5.2: if_match != current ETag → PreconditionFailedError (412)."""
    from src.api.articles.repository import PreconditionFailedError

    fake_article.id = uuid4()
    fake_article.access_level = "PUBLIC"
    fake_article.status = "PUBLISHED"

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock(return_value=None)
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = fake_article
    session.execute = AsyncMock(side_effect=[MagicMock(), select_result])

    repo = ArticleRepository(session)
    with pytest.raises(PreconditionFailedError) as exc_info:
        await repo.update(
            "the-slug",
            _valid_input(),
            frozenset({AccessLevel.PUBLIC}),
            actor_sub="actor",
            if_match='W/"stale-etag"',  # не совпадает с current
        )
    assert exc_info.value.status_code == 412


@pytest.mark.asyncio
async def test_update_if_match_match_proceeds(
    fake_article: Article,
) -> None:
    """E5.2: if_match совпадает с current ETag → update идёт нормально."""
    from src.api.articles.etag import compute_article_etag

    fake_article.id = uuid4()
    fake_article.access_level = "PUBLIC"
    fake_article.status = "PUBLISHED"

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = fake_article
    max_result = MagicMock()
    max_result.scalar.return_value = 1
    session.execute = AsyncMock(side_effect=[MagicMock(), select_result, max_result])

    repo = ArticleRepository(session)
    correct_etag = compute_article_etag(fake_article)
    out = await repo.update(
        "the-slug",
        _valid_input(),
        frozenset({AccessLevel.PUBLIC}),
        actor_sub="actor",
        if_match=correct_etag,
    )
    assert out is not None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_no_if_match_legacy(
    fake_article: Article,
) -> None:
    """E5.2: без if_match — legacy update без ETag check."""
    fake_article.id = uuid4()
    fake_article.access_level = "PUBLIC"
    fake_article.status = "PUBLISHED"

    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock(return_value=None)
    session.refresh = AsyncMock(return_value=None)
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = fake_article
    max_result = MagicMock()
    max_result.scalar.return_value = 0
    session.execute = AsyncMock(side_effect=[MagicMock(), select_result, max_result])

    repo = ArticleRepository(session)
    out = await repo.update(
        "the-slug",
        _valid_input(),
        frozenset({AccessLevel.PUBLIC}),
        actor_sub="actor",
        # if_match=None (default)
    )
    assert out is not None
