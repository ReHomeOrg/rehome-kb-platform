"""Unit-тесты для `/api/v1/tags` router.

Покрывает:
- Default / custom limit, q-фильтр.
- 422 при limit вне [1..200] и q длиннее 100.
- Empty/whitespace q → None.
- ADR-0003 security: guest без JWT получает frozenset({PUBLIC}) на
  стороне dependency; явно тестируем, что repo получает именно его.
- JWT с extended scope — repo получает расширенный access_levels.
- Invalid JWT (401) vs no JWT (200) — оптональная auth.
"""

from collections.abc import Callable, Iterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.auth.scope import AccessLevel
from src.api.main import app
from src.api.tags.repository import TagRepository, get_tag_repository


@pytest.fixture
def list_tags_mock() -> AsyncMock:
    """AsyncMock для TagRepository.list_tags — возвращаем mock напрямую,
    чтобы тесты имели type-safe доступ к `.call_args` без cast'ов."""
    return AsyncMock(return_value=[("договор", 3), ("аренда", 1)])


@pytest.fixture
def override_repo(list_tags_mock: AsyncMock) -> Iterator[AsyncMock]:
    """Override get_tag_repository dependency: репозиторий-обёртка с
    подменённым list_tags. Yielded value — AsyncMock для assert'ов."""
    repo = TagRepository.__new__(TagRepository)
    repo.list_tags = list_tags_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_tag_repository] = lambda: repo
    yield list_tags_mock
    app.dependency_overrides.pop(get_tag_repository, None)


def test_get_tags_returns_200_with_data_envelope(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.get("/api/v1/tags")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert body["data"] == [
        {"name": "договор", "article_count": 3},
        {"name": "аренда", "article_count": 1},
    ]


def test_get_tags_guest_uses_public_only_access_levels(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    """ADR-0003 security: guest без JWT → frozenset({PUBLIC})."""
    resp = client.get("/api/v1/tags")
    assert resp.status_code == 200
    call_kwargs = override_repo.call_args.kwargs
    call_args = override_repo.call_args.args
    levels: frozenset[AccessLevel] = call_args[0]
    assert levels == frozenset({AccessLevel.PUBLIC})
    assert call_kwargs == {"q": None, "limit": 50}


def test_get_tags_jwt_tenant_widens_access_levels(
    client: TestClient,
    override_repo: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """JWT с tenant роль → доступ к LOGGED дополнительно к PUBLIC."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/tags",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    levels: frozenset[AccessLevel] = override_repo.call_args.args[0]
    assert AccessLevel.PUBLIC in levels
    assert AccessLevel.LOGGED in levels


def test_get_tags_invalid_jwt_returns_401(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    """Невалидный JWT не должен молча деградировать до guest:
    `get_current_claims` поднимает InvalidTokenError. Это защита от
    confused-deputy: клиент явно отправил токен, мы обязаны валидировать.
    """
    resp = client.get(
        "/api/v1/tags",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401


def test_get_tags_q_passes_to_repo(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.get("/api/v1/tags", params={"q": "договор"})
    assert resp.status_code == 200
    assert override_repo.call_args.kwargs["q"] == "договор"


def test_get_tags_q_empty_normalised_to_none(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.get("/api/v1/tags", params={"q": ""})
    assert resp.status_code == 200
    assert override_repo.call_args.kwargs["q"] is None


def test_get_tags_q_whitespace_normalised_to_none(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.get("/api/v1/tags", params={"q": "   "})
    assert resp.status_code == 200
    assert override_repo.call_args.kwargs["q"] is None


def test_get_tags_q_too_long_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.get("/api/v1/tags", params={"q": "a" * 101})
    assert resp.status_code == 422


def test_get_tags_default_limit_50(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    client.get("/api/v1/tags")
    assert override_repo.call_args.kwargs["limit"] == 50


def test_get_tags_custom_limit(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    client.get("/api/v1/tags", params={"limit": 10})
    assert override_repo.call_args.kwargs["limit"] == 10


def test_get_tags_limit_zero_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.get("/api/v1/tags", params={"limit": 0})
    assert resp.status_code == 422


def test_get_tags_limit_above_max_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.get("/api/v1/tags", params={"limit": 201})
    assert resp.status_code == 422


def test_get_tags_negative_limit_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
) -> None:
    resp = client.get("/api/v1/tags", params={"limit": -1})
    assert resp.status_code == 422


def test_get_tags_empty_result(client: TestClient) -> None:
    """Repo возвращает пустой список → ответ `{data: []}`."""
    list_tags = AsyncMock(return_value=[])
    repo = TagRepository.__new__(TagRepository)
    repo.list_tags = list_tags  # type: ignore[method-assign]
    app.dependency_overrides[get_tag_repository] = lambda: repo
    try:
        resp = client.get("/api/v1/tags")
        assert resp.status_code == 200
        assert resp.json() == {"data": []}
    finally:
        app.dependency_overrides.pop(get_tag_repository, None)
