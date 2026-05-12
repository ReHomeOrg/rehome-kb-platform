"""Fixtures для unit-тестов tags.

`override_session_with_rows` подменяет `get_session` чтобы router-тесты
получали заранее заданный список tuple (name, article_count) без
реального Postgres.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.db import get_session
from src.api.main import app


@pytest.fixture
def session_returning_rows() -> Callable[[list[tuple[str, int]]], Any]:
    """Factory: AsyncSession-мок, возвращающий указанные rows."""

    def _build(rows: list[tuple[str, int]]) -> Any:
        result = MagicMock()
        row_objects = [MagicMock(name=name, article_count=count) for name, count in rows]
        for row, (name, count) in zip(row_objects, rows, strict=True):
            row.name = name
            row.article_count = count
        result.all.return_value = row_objects
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        return session

    return _build


@pytest.fixture
def override_session(
    session_returning_rows: Callable[[list[tuple[str, int]]], Any],
) -> Iterator[Callable[[list[tuple[str, int]]], None]]:
    """Override get_session dependency'и для TestClient.

    Использование:
        def test_foo(client, override_session):
            override_session([("договор", 3), ("аренда", 1)])
            client.get("/api/v1/tags")
    """
    holder: dict[str, Any] = {"session": None}

    async def _override() -> AsyncIterator[Any]:
        yield holder["session"]

    def _set(rows: list[tuple[str, int]]) -> None:
        holder["session"] = session_returning_rows(rows)

    app.dependency_overrides[get_session] = _override
    yield _set
    app.dependency_overrides.pop(get_session, None)
