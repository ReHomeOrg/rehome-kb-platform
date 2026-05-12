"""Fixtures для unit-тестов categories.

`override_session_with_rows` подменяет `get_session` чтобы router-тесты
получали заранее заданный flat-список row-объектов (id/slug/title/
description/parent_id/article_count) без реального Postgres.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from src.api.db import get_session
from src.api.main import app

Row = tuple[UUID, str, str, str | None, UUID | None, int]


@pytest.fixture
def session_returning_rows() -> Callable[[list[Row]], Any]:
    """Factory: AsyncSession-мок, возвращающий указанные rows."""

    def _build(rows: list[Row]) -> Any:
        result = MagicMock()
        row_objects = []
        for id_, slug, title, description, parent_id, count in rows:
            r = MagicMock()
            r.id = id_
            r.slug = slug
            r.title = title
            r.description = description
            r.parent_id = parent_id
            r.article_count = count
            row_objects.append(r)
        result.all.return_value = row_objects
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        return session

    return _build


@pytest.fixture
def override_session(
    session_returning_rows: Callable[[list[Row]], Any],
) -> Iterator[Callable[[list[Row]], None]]:
    """Override get_session dependency для TestClient."""
    holder: dict[str, Any] = {"session": None}

    async def _override() -> AsyncIterator[Any]:
        yield holder["session"]

    def _set(rows: list[Row]) -> None:
        holder["session"] = session_returning_rows(rows)

    app.dependency_overrides[get_session] = _override
    yield _set
    app.dependency_overrides.pop(get_session, None)
