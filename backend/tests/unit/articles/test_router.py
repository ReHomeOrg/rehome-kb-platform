"""Unit-тесты для GET /api/v1/articles/{slug}.

Проверяем router-уровень: dependency injection, валидация slug, 404
маскировка (ADR-0003). Реальный SQL фильтр покрыт test_repository.py.
"""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.articles.models import Article


def test_get_article_returns_200_when_found(
    client: TestClient,
    override_session: Callable[[Article | None], None],
    fake_article: Article,
) -> None:
    override_session(fake_article)
    response = client.get(f"/api/v1/articles/{fake_article.slug}")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == fake_article.slug
    assert body["title"] == fake_article.title
    assert body["status"] == "PUBLISHED"
    assert body["audience"] == "tenant"


def test_get_article_returns_404_when_missing(
    client: TestClient,
    override_session: Callable[[Article | None], None],
) -> None:
    """ADR-0003 masking: scope-out-of-reach неотличимо от nonexistent."""
    override_session(None)
    response = client.get("/api/v1/articles/nonexistent-slug")
    assert response.status_code == 404
    assert response.json()["detail"] == "Article not found"


@pytest.mark.parametrize(
    "bad_slug",
    [
        "Bad-Slug",  # uppercase
        "slug_with_underscore",
        "slug.with.dot",
        "slug with space",
        "slug/with/slash",
        "слаг-кириллица",
        "",  # empty (path won't match anyway, but documents intent)
    ],
)
def test_slug_validation_rejects_invalid_pattern(
    client: TestClient,
    bad_slug: str,
) -> None:
    """ADR-0006: slug — lowercase ASCII + digits + dash. Остальное → 4xx."""
    response = client.get(f"/api/v1/articles/{bad_slug}")
    # Любой 4xx подойдёт (422 если pattern сработал, 404 если path не матчит).
    assert response.status_code in (404, 422)


def test_slug_too_long_rejected(client: TestClient) -> None:
    long_slug = "a" * 201
    response = client.get(f"/api/v1/articles/{long_slug}")
    assert response.status_code == 422


def test_anonymous_user_sees_only_public_articles(
    client: TestClient,
    override_session: Callable[[Article | None], None],
    fake_article: Article,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Анонимный гость получает 404 для не-PUBLIC статьи.

    Здесь мы эмулируем поведение repository: для guest c {PUBLIC} запрос на
    статью с access_level=STAFF вернёт None (SQL фильтр отсечёт). Router-тест
    проверяет, что 404 действительно отдаётся (а не утечка через 500).
    """
    # Гость → repo вернёт None.
    override_session(None)
    response = client.get(f"/api/v1/articles/{fake_article.slug}")
    assert response.status_code == 404


def test_repository_receives_access_levels_from_dependency(
    client: TestClient,
    fake_article: Article,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Router передаёт frozenset[AccessLevel] из get_current_access_levels в repo.

    Это контрактный тест: подменяем ArticleRepository.get_by_slug и проверяем,
    что туда приходит правильный набор уровней (минимум {PUBLIC} для guest).
    """
    captured: dict[str, Any] = {}

    async def _fake_get_by_slug(self: Any, slug: str, access_levels: Any) -> Article | None:
        captured["slug"] = slug
        captured["access_levels"] = access_levels
        return fake_article

    monkeypatch.setattr(
        "src.api.articles.router.ArticleRepository.get_by_slug",
        _fake_get_by_slug,
    )

    # Подменяем session-dependency на пустышку (метод всё равно замокан).
    from src.api.db import get_session
    from src.api.main import app

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session
    try:
        response = client.get("/api/v1/articles/some-slug")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    assert captured["slug"] == "some-slug"
    # Гость (без токена) → должен получить минимум {PUBLIC}.
    assert {lvl.value for lvl in captured["access_levels"]} == {"PUBLIC"}
