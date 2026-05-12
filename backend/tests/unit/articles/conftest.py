"""Fixtures для unit-тестов articles.

`override_get_session` подменяет `get_session` dependency на наш фейковый
session, чтобы router-тесты не требовали реальный Postgres.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.articles.models import Article
from src.api.db import get_session
from src.api.main import app


@pytest.fixture
def fake_article() -> Article:
    """Полностью заполненный Article — для возврата из mock-repository."""
    from datetime import UTC, datetime

    a = Article()
    a.id = uuid4()
    a.slug = "kak-podpisat-dogovor"
    a.title = "Как подписать договор"
    a.summary = "Краткая инструкция"
    a.body_markdown = "# Шаг 1\n..."
    a.audience = "tenant"
    a.language = "ru"
    a.category = "rental"
    a.tags = ["договор", "наниматель"]
    a.access_level = "PUBLIC"
    a.status = "PUBLISHED"
    a.published_at = datetime(2026, 5, 11, tzinfo=UTC)
    a.created_at = datetime(2026, 5, 11, tzinfo=UTC)
    a.updated_at = datetime(2026, 5, 11, tzinfo=UTC)
    return a


@pytest.fixture
def session_returning(fake_article: Article) -> Callable[[Article | None], Any]:
    """Factory: создаёт AsyncSession-мок, который вернёт указанный Article (или None)."""

    def _build(article: Article | None) -> Any:
        result = MagicMock()
        result.scalar_one_or_none.return_value = article
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        return session

    return _build


@pytest.fixture
def override_session(
    session_returning: Callable[[Article | None], Any],
) -> Iterator[Callable[[Article | None], None]]:
    """Override get_session dependency'и для TestClient.

    Использование:
        def test_foo(client, override_session, fake_article):
            override_session(fake_article)
            client.get("/api/v1/articles/...")
    """
    holder: dict[str, Any] = {"session": None}

    async def _override() -> AsyncIterator[Any]:
        yield holder["session"]

    def _set(article: Article | None) -> None:
        holder["session"] = session_returning(article)

    app.dependency_overrides[get_session] = _override
    yield _set
    app.dependency_overrides.pop(get_session, None)
