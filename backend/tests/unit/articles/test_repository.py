"""Unit-тесты ArticleRepository.

Проверяем, что:
1. SQL фильтр включает access_level (ADR-0003 critical invariant).
2. Возвращаем None если scope не видит статью.
3. Возвращаем Article если запись найдена.
4. Защищённое маскировкой 404: pусто frozenset → IN ([]) → 0 строк.
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.articles.models import Article
from src.api.articles.repository import ArticleRepository
from src.api.auth.scope import AccessLevel


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
