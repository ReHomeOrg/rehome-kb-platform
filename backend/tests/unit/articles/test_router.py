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
    # OpenAPI ArticleSummary требует access_level в каждом ответе.
    assert body["access_level"] == "PUBLIC"


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
    ],
)
def test_slug_validation_rejects_invalid_pattern(
    client: TestClient,
    bad_slug: str,
) -> None:
    """ADR-0006: slug — lowercase ASCII + digits + dash. Остальное → 4xx.

    Кейс пустого slug опущен: после добавления `GET /api/v1/articles`
    (list) пустой path-параметр приведёт к редиректу на list, что не
    тестирует валидацию pattern. Pattern валидируется FastAPI напрямую
    для non-empty path values.
    """
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


# ============================================================
# GET /api/v1/articles — list endpoint
# ============================================================


def _override_list_filtered(
    monkeypatch: pytest.MonkeyPatch,
    return_rows: list[Article],
    has_more: bool = False,
    capture: dict[str, Any] | None = None,
) -> None:
    """Подменяет ArticleRepository.list_filtered и пишет вызов в capture."""

    async def _fake(
        self: Any,
        access_levels: frozenset[Any],
        **kwargs: Any,
    ) -> tuple[list[Article], bool]:
        if capture is not None:
            capture["access_levels"] = access_levels
            capture.update(kwargs)
        return return_rows, has_more

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.list_filtered", _fake)

    # Подменяем session-dependency (репозиторий всё равно замокан).
    from src.api.db import get_session
    from src.api.main import app

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session


def _cleanup_session_override() -> None:
    from src.api.db import get_session
    from src.api.main import app

    app.dependency_overrides.pop(get_session, None)


def test_list_articles_returns_200_with_summaries(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    _override_list_filtered(monkeypatch, [fake_article], has_more=False)
    try:
        response = client.get("/api/v1/articles")
    finally:
        _cleanup_session_override()
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1
    assert body["data"][0]["slug"] == fake_article.slug
    # ArticleSummary: body_markdown НЕ в ответе.
    assert "body_markdown" not in body["data"][0]
    # pagination
    assert body["pagination"]["cursor_next"] is None
    assert body["pagination"]["has_more"] is False


def test_list_articles_empty_returns_200_empty_array(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _override_list_filtered(monkeypatch, [], has_more=False)
    try:
        response = client.get("/api/v1/articles")
    finally:
        _cleanup_session_override()
    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["pagination"]["has_more"] is False


def test_list_articles_invalid_cursor_returns_400(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _override_list_filtered(monkeypatch, [], has_more=False)
    try:
        response = client.get("/api/v1/articles?cursor=это-не-base64-©®")
    finally:
        _cleanup_session_override()
    assert response.status_code == 400
    assert "cursor" in response.json()["detail"].lower()


def test_list_articles_limit_too_large_returns_422(client: TestClient) -> None:
    response = client.get("/api/v1/articles?limit=101")
    assert response.status_code == 422


def test_list_articles_limit_zero_returns_422(client: TestClient) -> None:
    response = client.get("/api/v1/articles?limit=0")
    assert response.status_code == 422


def test_list_articles_default_limit_is_20(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_list_filtered(monkeypatch, [], capture=capture)
    try:
        client.get("/api/v1/articles")
    finally:
        _cleanup_session_override()
    assert capture["limit"] == 20


def test_list_articles_passes_access_levels_from_dependency(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_list_filtered(monkeypatch, [], capture=capture)
    try:
        # Без токена — гость → access_levels = {PUBLIC}.
        client.get("/api/v1/articles")
    finally:
        _cleanup_session_override()
    assert {lvl.value for lvl in capture["access_levels"]} == {"PUBLIC"}


def test_list_articles_returns_cursor_next_when_has_more(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    """has_more=True → cursor_next содержит непустую opaque строку."""
    _override_list_filtered(monkeypatch, [fake_article], has_more=True)
    try:
        response = client.get("/api/v1/articles?limit=1")
    finally:
        _cleanup_session_override()
    body = response.json()
    assert body["pagination"]["has_more"] is True
    assert isinstance(body["pagination"]["cursor_next"], str)
    assert len(body["pagination"]["cursor_next"]) > 0


def test_list_articles_unknown_category_returns_200_not_422(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAPI ограничивает category enum'ом; до E4 принимаем любой str."""
    _override_list_filtered(monkeypatch, [], has_more=False)
    try:
        response = client.get("/api/v1/articles?category=not-a-real-category")
    finally:
        _cleanup_session_override()
    assert response.status_code == 200
    assert response.json()["data"] == []


def test_list_articles_filters_passed_to_repo(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_list_filtered(monkeypatch, [], capture=capture)
    try:
        client.get("/api/v1/articles?category=guide&audience=tenant&language=ru")
    finally:
        _cleanup_session_override()
    assert capture["category"] == "guide"
    assert capture["audience"] == "tenant"
    assert capture["language"] == "ru"


def test_list_articles_valid_cursor_decoded_and_passed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from src.api.articles.cursor import encode_cursor

    capture: dict[str, Any] = {}
    _override_list_filtered(monkeypatch, [], capture=capture)
    ts = datetime(2026, 5, 12, 10, 30, tzinfo=UTC)
    aid = uuid4()
    cursor = encode_cursor(ts, aid)
    try:
        client.get(f"/api/v1/articles?cursor={cursor}")
    finally:
        _cleanup_session_override()
    decoded_ts, decoded_id = capture["cursor"]
    assert decoded_ts == ts
    assert decoded_id == aid


def test_list_articles_no_filter_passes_none_to_repo(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_list_filtered(monkeypatch, [], capture=capture)
    try:
        client.get("/api/v1/articles")
    finally:
        _cleanup_session_override()
    assert capture["category"] is None
    assert capture["audience"] is None
    assert capture["language"] is None
    assert capture["cursor"] is None
