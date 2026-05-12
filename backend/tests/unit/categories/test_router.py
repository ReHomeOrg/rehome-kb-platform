"""Unit-тесты для `/api/v1/categories` router.

Покрывает:
- 200 с tree response envelope.
- Guest без JWT → access_levels={PUBLIC} в repo call.
- JWT tenant расширяет access_levels.
- Invalid JWT → 401 (не silent-degrade).
- Empty repo → `{data: []}`.
- Tree-структура передаётся клиенту с рекурсивным children.
"""

from collections.abc import Callable, Iterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.auth.scope import AccessLevel
from src.api.categories.repository import (
    CategoryNode,
    CategoryRepository,
    get_category_repository,
)
from src.api.main import app


@pytest.fixture
def list_tree_mock() -> AsyncMock:
    """AsyncMock для CategoryRepository.list_tree."""
    return AsyncMock(return_value=[])


@pytest.fixture
def override_repo(list_tree_mock: AsyncMock) -> Iterator[AsyncMock]:
    repo = CategoryRepository.__new__(CategoryRepository)
    repo.list_tree = list_tree_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_category_repository] = lambda: repo
    yield list_tree_mock
    app.dependency_overrides.pop(get_category_repository, None)


def _node(slug: str, count: int = 0, children: list[CategoryNode] | None = None) -> CategoryNode:
    return CategoryNode(
        id=uuid4(),
        slug=slug,
        title=slug.capitalize(),
        description=None,
        parent_id=None,
        article_count=count,
        children=children or [],
    )


def test_get_categories_empty_returns_data_list(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.get("/api/v1/categories")
    assert resp.status_code == 200
    assert resp.json() == {"data": []}


def test_get_categories_returns_tree(
    client: TestClient,
    list_tree_mock: AsyncMock,
) -> None:
    """Tree returned with nested children."""
    child = _node("renting", count=2)
    root = _node("housing", count=5, children=[child])
    list_tree_mock.return_value = [root]

    repo = CategoryRepository.__new__(CategoryRepository)
    repo.list_tree = list_tree_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_category_repository] = lambda: repo
    try:
        resp = client.get("/api/v1/categories")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1
        r = body["data"][0]
        assert r["slug"] == "housing"
        assert r["article_count"] == 5
        assert r["title"] == "Housing"
        assert r["description"] is None
        assert len(r["children"]) == 1
        assert r["children"][0]["slug"] == "renting"
        assert r["children"][0]["article_count"] == 2
        assert r["children"][0]["children"] == []
    finally:
        app.dependency_overrides.pop(get_category_repository, None)


def test_get_categories_guest_uses_public_only_access_levels(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    """ADR-0003 security: guest без JWT → frozenset({PUBLIC})."""
    resp = client.get("/api/v1/categories")
    assert resp.status_code == 200
    levels: frozenset[AccessLevel] = override_repo.call_args.args[0]
    assert levels == frozenset({AccessLevel.PUBLIC})


def test_get_categories_jwt_tenant_widens_access_levels(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/categories",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    levels: frozenset[AccessLevel] = override_repo.call_args.args[0]
    assert AccessLevel.PUBLIC in levels
    assert AccessLevel.LOGGED in levels


def test_get_categories_invalid_jwt_returns_401(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    """Invalid JWT не silent-degrade — confused-deputy защита."""
    resp = client.get(
        "/api/v1/categories",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401
