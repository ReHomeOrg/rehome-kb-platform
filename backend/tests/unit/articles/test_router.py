"""Unit-тесты для GET /api/v1/articles/{slug}.

Проверяем router-уровень: dependency injection, валидация slug, 404
маскировка (ADR-0003). Реальный SQL фильтр покрыт test_repository.py.
"""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

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


# ============================================================
# POST /api/v1/articles — write endpoint (E4.1)
# ============================================================


def _post_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "slug": "new-article",
        "title": "Тайтл",
        "body_markdown": "# Body",
        "category": "guide",
        "audience": "tenant",
        "access_level": "PUBLIC",
    }
    base.update(overrides)
    return base


def _override_post_create(
    monkeypatch: pytest.MonkeyPatch,
    return_article: Article | None = None,
    raise_exc: Exception | None = None,
) -> None:
    """Подменяет ArticleRepository.create + create_atomic (ADR-0026 Slice 1)."""

    async def _fake(self: Any, payload: Any, *, actor_sub: str) -> Article:
        if raise_exc is not None:
            raise raise_exc
        assert return_article is not None
        # Имитируем server-defaults через подстановку из payload.
        return_article.slug = payload.slug
        return_article.title = payload.title
        return_article.body_markdown = payload.body_markdown
        return_article.category = payload.category
        return_article.audience = payload.audience
        return_article.access_level = payload.access_level.value
        return_article.status = payload.status
        return_article.language = payload.language
        return_article.tags = list(payload.tags)
        return return_article

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create", _fake)
    # ADR-0026 Slice 1: handler теперь использует create_atomic.
    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create_atomic", _fake)

    from unittest.mock import AsyncMock, MagicMock

    from src.api.db import get_session
    from src.api.main import app

    # Session mock с поддержкой commit/rollback/refresh (handler теперь
    # делает explicit session.commit() per ADR-0026 Slice 1 atomic flow).
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    async def _session_factory() -> Any:
        yield session

    app.dependency_overrides[get_session] = _session_factory


def test_post_articles_401_without_token(client: TestClient) -> None:
    """Гость без токена → 401 (через require_authenticated)."""
    response = client.post("/api/v1/articles", json=_post_payload())
    assert response.status_code == 401


def test_post_articles_401_with_invalid_token(client: TestClient) -> None:
    """Невалидный JWT → 401 (через get_current_claims → InvalidTokenError)."""
    response = client.post(
        "/api/v1/articles",
        json=_post_payload(),
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert response.status_code == 401


def test_post_articles_403_when_tenant_scope(
    client: TestClient,
    make_jwt: Callable[..., str],
) -> None:
    """tenant scope не содержит STAFF → 403 (через require_access_level)."""
    token = make_jwt(roles=["tenant"])
    response = client.post(
        "/api/v1/articles",
        json=_post_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_post_articles_201_when_staff_admin_creates_public(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    _override_post_create(monkeypatch, return_article=fake_article)
    try:
        token = make_jwt(roles=["staff_admin"], sub="admin-user-sub")
        response = client.post(
            "/api/v1/articles",
            json=_post_payload(slug="brand-new", access_level="PUBLIC"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 201, response.text
    assert response.headers["Location"] == "/api/v1/articles/brand-new"
    body = response.json()
    assert body["slug"] == "brand-new"
    assert body["access_level"] == "PUBLIC"


@pytest.mark.security
def test_post_articles_403_when_staff_admin_tries_hr_restricted(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    """ADR-0003 critical write-extension: staff_admin БЕЗ HR_RESTRICTED → 403."""
    _override_post_create(monkeypatch, return_article=fake_article)
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.post(
            "/api/v1/articles",
            json=_post_payload(access_level="HR_RESTRICTED"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 403
    assert "access_level" in response.json()["detail"].lower()


@pytest.mark.security
def test_post_articles_201_when_staff_hr_creates_hr_restricted(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    """Positive: staff_hr ИМЕЕТ HR_RESTRICTED level → может создать.

    Этот тест защищает от регрессии в `SCOPE_TO_ACCESS_LEVELS` map —
    если кто-то случайно уберёт HR_RESTRICTED из staff_hr, тест упадёт.
    """
    _override_post_create(monkeypatch, return_article=fake_article)
    try:
        token = make_jwt(roles=["staff_hr"], sub="hr-user")
        response = client.post(
            "/api/v1/articles",
            json=_post_payload(slug="hr-article", access_level="HR_RESTRICTED"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["access_level"] == "HR_RESTRICTED"


@pytest.mark.parametrize(
    "broken_payload",
    [
        {},  # пустой
        {
            "slug": "ok",
            "title": "ok",
            "body_markdown": "x",
            "category": "c",
            "audience": "a",
        },  # нет access_level
        {
            **{
                "slug": "BadSlug",
                "title": "x",
                "body_markdown": "x",
                "category": "c",
                "audience": "a",
                "access_level": "PUBLIC",
            }
        },  # bad slug pattern
        {
            **{
                "slug": "ok",
                "title": "x",
                "body_markdown": "x",
                "category": "c",
                "audience": "a",
                "access_level": "INVALID",
            }
        },  # bad enum
        {
            **{
                "slug": "ok",
                "title": "x",
                "body_markdown": "x",
                "category": "c",
                "audience": "a",
                "access_level": "PUBLIC",
                "extra": "field",
            }
        },  # extra forbidden
    ],
)
def test_post_articles_422_when_payload_invalid(
    client: TestClient,
    make_jwt: Callable[..., str],
    broken_payload: dict[str, Any],
) -> None:
    """Pydantic schema валидирует до router-логики → 422.

    Даже без токена 422 теоретически возможен, но FastAPI обычно сначала
    запускает body parsing — поэтому добавляем токен, чтобы не получить
    401 раньше валидации (мы тестируем именно валидацию).
    """
    token = make_jwt(roles=["staff_admin"])
    response = client.post(
        "/api/v1/articles",
        json=broken_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422, response.text


def test_post_articles_409_when_slug_exists(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.api.articles.repository import SlugConflictError

    _override_post_create(monkeypatch, raise_exc=SlugConflictError("dup"))
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.post(
            "/api/v1/articles",
            json=_post_payload(slug="dup"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 409


def test_post_articles_audit_log_emitted_without_content(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ФЗ-152: audit-log содержит метаданные, НЕ body_markdown/title/summary."""
    import logging

    _override_post_create(monkeypatch, return_article=fake_article)
    try:
        token = make_jwt(roles=["staff_admin"], sub="actor-sub-uuid")
        caplog.set_level(logging.INFO, logger="rehome.kb.audit")
        response = client.post(
            "/api/v1/articles",
            json=_post_payload(slug="audit-test", access_level="PUBLIC"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 201
    # Запись присутствует
    audit_records = [r for r in caplog.records if r.name == "rehome.kb.audit"]
    assert len(audit_records) == 1
    rec = audit_records[0]
    assert rec.getMessage() == "articles.created"
    # Метаданные присутствуют.
    assert getattr(rec, "actor_sub", None) == "actor-sub-uuid"
    assert getattr(rec, "slug", None) == "audit-test"
    assert getattr(rec, "access_level", None) == "PUBLIC"
    # Контент НЕ должен утекать.
    for attr in ("body_markdown", "title", "summary", "short_answer"):
        assert not hasattr(rec, attr), f"Audit log утекает '{attr}'"


def test_post_articles_actor_sub_from_jwt_not_payload(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Security: actor_sub берётся из JWT, не из payload. Атака с подменой автора отклоняется."""
    import logging

    _override_post_create(monkeypatch, return_article=fake_article)
    try:
        token = make_jwt(roles=["staff_admin"], sub="real-actor")
        caplog.set_level(logging.INFO, logger="rehome.kb.audit")
        # Попытка передать `actor_sub` в payload → должна быть отвергнута
        # (extra='forbid' в schema).
        response = client.post(
            "/api/v1/articles",
            json={**_post_payload(slug="x"), "actor_sub": "spoofed-actor"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    # Schema отвергает unknown field → 422.
    assert response.status_code == 422


@pytest.mark.security
def test_post_articles_staff_support_cannot_create_legal(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    """staff_support имеет STAFF и ниже, но не LEGAL → 403."""
    _override_post_create(monkeypatch, return_article=fake_article)
    try:
        token = make_jwt(roles=["staff_support"])
        response = client.post(
            "/api/v1/articles",
            json=_post_payload(access_level="LEGAL"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 403


# ============================================================
# PUT /api/v1/articles/{slug} — replace endpoint (E4.3)
# ============================================================


def _put_payload(slug: str = "my-slug", **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "slug": slug,
        "title": "Updated Title",
        "body_markdown": "# Updated",
        "category": "guide",
        "audience": "tenant",
        "access_level": "PUBLIC",
    }
    base.update(overrides)
    return base


def _override_put_update(
    monkeypatch: pytest.MonkeyPatch,
    return_value: tuple[Article, str, str] | None,
) -> None:
    """Подменяет ArticleRepository.update."""

    async def _fake(
        self: Any,
        slug: str,
        payload: Any,
        access_levels: frozenset[Any],
        *,
        actor_sub: str,
        if_match: str | None = None,
    ) -> tuple[Article, str, str] | None:
        if return_value is None:
            return None
        article, old_al, old_st = return_value
        article.slug = slug
        article.title = payload.title
        article.body_markdown = payload.body_markdown
        article.category = payload.category
        article.audience = payload.audience
        article.access_level = payload.access_level.value
        article.status = payload.status
        article.language = payload.language
        article.tags = list(payload.tags)
        return article, old_al, old_st

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.update", _fake)

    from src.api.db import get_session
    from src.api.main import app

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session


def test_put_articles_401_without_token(client: TestClient) -> None:
    response = client.put("/api/v1/articles/my-slug", json=_put_payload())
    assert response.status_code == 401


def test_put_articles_403_when_tenant_scope(
    client: TestClient, make_jwt: Callable[..., str]
) -> None:
    token = make_jwt(roles=["tenant"])
    response = client.put(
        "/api/v1/articles/my-slug",
        json=_put_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_put_articles_200_when_staff_admin_updates_public(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    _override_put_update(monkeypatch, (fake_article, "PUBLIC", "PUBLISHED"))
    try:
        token = make_jwt(roles=["staff_admin"], sub="admin-user")
        response = client.put(
            "/api/v1/articles/my-slug",
            json=_put_payload("my-slug", access_level="PUBLIC"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slug"] == "my-slug"
    assert body["title"] == "Updated Title"


def test_put_articles_404_when_article_not_found(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _override_put_update(monkeypatch, None)
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.put(
            "/api/v1/articles/missing",
            json=_put_payload("missing"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 404


@pytest.mark.security
def test_put_articles_404_when_scope_cannot_see(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0003 source mask: репозиторий вернул None для out-of-scope → 404."""
    _override_put_update(monkeypatch, None)
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.put(
            "/api/v1/articles/hr-secret",
            json=_put_payload("hr-secret", access_level="PUBLIC"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 404


@pytest.mark.security
def test_put_articles_403_when_target_access_level_not_writable(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    """ADR-0003 target Level-2: staff_admin не может ставить HR_RESTRICTED → 403.

    Target check ДО source check — клиент не получает информацию о
    существовании источника через 404 vs 403 timing.
    """
    _override_put_update(monkeypatch, (fake_article, "PUBLIC", "PUBLISHED"))
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.put(
            "/api/v1/articles/my-slug",
            json=_put_payload("my-slug", access_level="HR_RESTRICTED"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 403


def test_put_articles_422_when_slug_mismatch_path_vs_body(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    """Slug change через PUT отвергается — path = identifier."""
    _override_put_update(monkeypatch, (fake_article, "PUBLIC", "PUBLISHED"))
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.put(
            "/api/v1/articles/path-slug",
            json=_put_payload("body-slug"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 422
    assert "slug" in response.json()["detail"].lower()


@pytest.mark.parametrize(
    "broken_payload",
    [
        {},
        {
            "slug": "ok",
            "title": "x",
            "body_markdown": "x",
            "category": "c",
            "audience": "a",
        },
        {
            "slug": "ok",
            "title": "x",
            "body_markdown": "x",
            "category": "c",
            "audience": "a",
            "access_level": "PUBLIC",
            "extra": "field",
        },
    ],
)
def test_put_articles_422_when_payload_invalid(
    client: TestClient,
    make_jwt: Callable[..., str],
    broken_payload: dict[str, Any],
) -> None:
    token = make_jwt(roles=["staff_admin"])
    response = client.put(
        "/api/v1/articles/ok",
        json=broken_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


@pytest.mark.security
def test_put_articles_200_when_staff_hr_updates_hr_restricted(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    """Positive matrix guard: staff_hr ИМЕЕТ HR_RESTRICTED level → 200."""
    _override_put_update(monkeypatch, (fake_article, "HR_RESTRICTED", "PUBLISHED"))
    try:
        token = make_jwt(roles=["staff_hr"], sub="hr-user")
        response = client.put(
            "/api/v1/articles/hr-doc",
            json=_put_payload("hr-doc", access_level="HR_RESTRICTED"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 200, response.text


def test_put_articles_audit_log_emitted_without_content(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ФЗ-152: audit-log содержит метаданные дельты, НЕ body_markdown/title."""
    import logging

    _override_put_update(monkeypatch, (fake_article, "PUBLIC", "DRAFT"))
    try:
        token = make_jwt(roles=["staff_admin"], sub="actor-uuid")
        caplog.set_level(logging.INFO, logger="rehome.kb.audit")
        response = client.put(
            "/api/v1/articles/my-slug",
            json=_put_payload("my-slug", access_level="LOGGED", status="PUBLISHED"),
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 200
    audit_records = [r for r in caplog.records if r.name == "rehome.kb.audit"]
    assert len(audit_records) == 1
    rec = audit_records[0]
    assert rec.getMessage() == "articles.updated"
    assert getattr(rec, "actor_sub", None) == "actor-uuid"
    assert getattr(rec, "slug", None) == "my-slug"
    assert getattr(rec, "old_access_level", None) == "PUBLIC"
    assert getattr(rec, "new_access_level", None) == "LOGGED"
    assert getattr(rec, "old_status", None) == "DRAFT"
    assert getattr(rec, "new_status", None) == "PUBLISHED"
    for attr in ("body_markdown", "title", "summary", "short_answer"):
        assert not hasattr(rec, attr), f"Audit log утекает '{attr}'"


# ============================================================
# DELETE /api/v1/articles/{slug} — soft-delete endpoint (E4.4)
# ============================================================


def _override_delete_archive(
    monkeypatch: pytest.MonkeyPatch,
    return_value: tuple[str, str] | None,
) -> None:
    """Подменяет ArticleRepository.archive."""

    async def _fake(
        self: Any,
        slug: str,
        access_levels: frozenset[Any],
        *,
        actor_sub: str,
    ) -> tuple[str, str] | None:
        return return_value

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.archive", _fake)

    from src.api.db import get_session
    from src.api.main import app

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session


def test_delete_articles_401_without_token(client: TestClient) -> None:
    response = client.delete("/api/v1/articles/my-slug")
    assert response.status_code == 401


def test_delete_articles_403_when_tenant_scope(
    client: TestClient, make_jwt: Callable[..., str]
) -> None:
    token = make_jwt(roles=["tenant"])
    response = client.delete(
        "/api/v1/articles/my-slug",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_delete_articles_204_when_staff_admin_archives_public(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _override_delete_archive(monkeypatch, ("PUBLISHED", "PUBLIC"))
    try:
        token = make_jwt(roles=["staff_admin"], sub="admin-user")
        response = client.delete(
            "/api/v1/articles/my-slug",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 204
    assert response.content == b""  # 204 No Content


def test_delete_articles_404_when_article_not_found(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _override_delete_archive(monkeypatch, None)
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.delete(
            "/api/v1/articles/missing",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 404


@pytest.mark.security
def test_delete_articles_404_when_scope_cannot_see(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0003 source mask: репозиторий вернул None для out-of-scope → 404."""
    _override_delete_archive(monkeypatch, None)
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.delete(
            "/api/v1/articles/hr-secret",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 404


def test_delete_articles_204_idempotent_for_already_archived(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RFC 7231 идемпотентность: повторная DELETE → 204 (was_status=ARCHIVED)."""
    _override_delete_archive(monkeypatch, ("ARCHIVED", "PUBLIC"))
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.delete(
            "/api/v1/articles/already-archived",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 204


def test_delete_articles_audit_log_emitted_without_content(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ФЗ-152: audit-log содержит метаданные (actor_sub, slug, was_status,
    was_access_level), НЕ content."""
    import logging

    _override_delete_archive(monkeypatch, ("PUBLISHED", "STAFF"))
    try:
        token = make_jwt(roles=["staff_admin"], sub="actor-uuid")
        caplog.set_level(logging.INFO, logger="rehome.kb.audit")
        response = client.delete(
            "/api/v1/articles/my-slug",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 204
    audit_records = [r for r in caplog.records if r.name == "rehome.kb.audit"]
    assert len(audit_records) == 1
    rec = audit_records[0]
    assert rec.getMessage() == "articles.archived"
    assert getattr(rec, "actor_sub", None) == "actor-uuid"
    assert getattr(rec, "slug", None) == "my-slug"
    assert getattr(rec, "was_status", None) == "PUBLISHED"
    assert getattr(rec, "was_access_level", None) == "STAFF"
    # Контент НЕ должен утекать.
    for attr in ("body_markdown", "title", "summary", "short_answer"):
        assert not hasattr(rec, attr), f"Audit log утекает '{attr}'"


@pytest.mark.security
def test_delete_articles_staff_hr_can_archive_hr_restricted(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive matrix (per Reviewer N5): staff_hr ИМЕЕТ HR_RESTRICTED → 204."""
    _override_delete_archive(monkeypatch, ("PUBLISHED", "HR_RESTRICTED"))
    try:
        token = make_jwt(roles=["staff_hr"], sub="hr-user")
        response = client.delete(
            "/api/v1/articles/hr-doc",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 204


@pytest.mark.security
def test_delete_articles_staff_admin_cannot_archive_hr_restricted(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative matrix (per Reviewer N5): staff_admin БЕЗ HR_RESTRICTED → 404
    (source mask). Репозиторий возвращает None — статья не видна.
    """
    _override_delete_archive(monkeypatch, None)
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.delete(
            "/api/v1/articles/hr-doc",
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 404


# ============================================================
# GET /api/v1/articles?tags=... — tags filter (E2.4)
# ============================================================


def _override_list_filtered_capture_tags(
    monkeypatch: pytest.MonkeyPatch,
    capture: dict[str, Any],
) -> None:
    """Подменяет list_filtered, сохраняя `tags` kwarg."""

    async def _fake(
        self: Any,
        access_levels: frozenset[Any],
        **kwargs: Any,
    ) -> tuple[list[Article], bool]:
        capture.update(kwargs)
        return [], False

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.list_filtered", _fake)

    from src.api.db import get_session
    from src.api.main import app

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session


def test_list_articles_tags_csv_parsed_to_list(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_list_filtered_capture_tags(monkeypatch, capture)
    try:
        client.get("/api/v1/articles?tags=договор,наниматель")
    finally:
        _cleanup_session_override()
    assert capture["tags"] == ["договор", "наниматель"]


def test_list_articles_tags_strip_whitespace(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_list_filtered_capture_tags(monkeypatch, capture)
    try:
        client.get("/api/v1/articles?tags=%20%20договор%20,%20наниматель%20%20")
    finally:
        _cleanup_session_override()
    assert capture["tags"] == ["договор", "наниматель"]


def test_list_articles_tags_dedupe(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_list_filtered_capture_tags(monkeypatch, capture)
    try:
        client.get("/api/v1/articles?tags=foo,foo,bar,foo")
    finally:
        _cleanup_session_override()
    assert capture["tags"] == ["foo", "bar"]


def test_list_articles_tags_empty_string_treated_as_none(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_list_filtered_capture_tags(monkeypatch, capture)
    try:
        client.get("/api/v1/articles?tags=")
    finally:
        _cleanup_session_override()
    assert capture["tags"] is None


def test_list_articles_tags_whitespace_only_treated_as_none(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_list_filtered_capture_tags(monkeypatch, capture)
    try:
        client.get("/api/v1/articles?tags=%20%20%20")
    finally:
        _cleanup_session_override()
    assert capture["tags"] is None


def test_list_articles_tags_only_commas_treated_as_none(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`?tags=,,,` → strip filter empty → None (фильтр не применяется)."""
    capture: dict[str, Any] = {}
    _override_list_filtered_capture_tags(monkeypatch, capture)
    try:
        client.get("/api/v1/articles?tags=,,,")
    finally:
        _cleanup_session_override()
    assert capture["tags"] is None


def test_list_articles_tags_lowercase_normalization(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`?tags=Договор,ДОГОВОР` → lowercase + dedup → `["договор"]` в repo (#346)."""
    capture: dict[str, Any] = {}
    _override_list_filtered_capture_tags(monkeypatch, capture)
    try:
        client.get("/api/v1/articles?tags=Договор,ДОГОВОР,Сервис")
    finally:
        _cleanup_session_override()
    assert capture["tags"] == ["договор", "сервис"]


def test_list_articles_too_many_tags_returns_422(client: TestClient) -> None:
    """>10 тегов → 422."""
    tags = ",".join(f"tag{i}" for i in range(11))
    response = client.get(f"/api/v1/articles?tags={tags}")
    assert response.status_code == 422
    # Detail не echo'ит user-input (без конкретных tags в сообщении).
    detail = response.json()["detail"]
    assert "10" in str(detail)


def test_list_articles_tag_too_long_returns_422(client: TestClient) -> None:
    """Тег >50 символов → 422."""
    long_tag = "a" * 51
    response = client.get(f"/api/v1/articles?tags={long_tag}")
    assert response.status_code == 422


def test_list_articles_tags_no_filter_passes_none(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_list_filtered_capture_tags(monkeypatch, capture)
    try:
        client.get("/api/v1/articles")
    finally:
        _cleanup_session_override()
    assert capture["tags"] is None


def test_list_articles_tags_query_max_length_enforced(client: TestClient) -> None:
    """`?tags=` с >600 символов отвергается Query max_length (FastAPI 422)."""
    raw = "a" * 601
    response = client.get(f"/api/v1/articles?tags={raw}")
    assert response.status_code == 422


# ============================================================
# GET /api/v1/articles/{slug}/history (E2.3 #36)
# ============================================================


def _override_list_versions(
    monkeypatch: pytest.MonkeyPatch,
    return_value: list[Any] | None,
) -> None:
    """Подменяет ArticleRepository.list_versions."""

    async def _fake(
        self: Any,
        slug: str,
        access_levels: frozenset[Any],
    ) -> list[Any] | None:
        return return_value

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.list_versions", _fake)

    from src.api.db import get_session
    from src.api.main import app

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session


def test_get_history_200_returns_versions_desc(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from src.api.articles.models import ArticleVersion

    aid = uuid4()
    v2 = ArticleVersion(
        article_id=aid,
        version=2,
        event="UPDATE",
        author_sub="user-2",
        old_status="DRAFT",
        new_status="PUBLISHED",
        old_access_level="PUBLIC",
        new_access_level="PUBLIC",
        changes_summary="Updated",
    )
    v2.changed_at = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    v1 = ArticleVersion(
        article_id=aid,
        version=1,
        event="CREATE",
        author_sub="user-1",
        new_status="DRAFT",
        new_access_level="PUBLIC",
        changes_summary="Article created",
    )
    v1.changed_at = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    _override_list_versions(monkeypatch, [v2, v1])  # already DESC
    try:
        response = client.get("/api/v1/articles/some-slug/history")
    finally:
        _cleanup_session_override()
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["data"]) == 2
    # Map: author_sub → author per OpenAPI.
    assert body["data"][0]["version"] == 2
    assert body["data"][0]["author"] == "user-2"
    assert body["data"][0]["event"] == "UPDATE"
    assert body["data"][1]["version"] == 1
    assert body["data"][1]["author"] == "user-1"
    assert body["data"][1]["event"] == "CREATE"
    # Контент НЕ возвращается (body_markdown/title — нет).
    for item in body["data"]:
        assert "body_markdown" not in item
        assert "title" not in item


def test_get_history_404_when_article_not_found(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0003 source-mask: invisible article → 404."""
    _override_list_versions(monkeypatch, None)
    try:
        response = client.get("/api/v1/articles/missing/history")
    finally:
        _cleanup_session_override()
    assert response.status_code == 404


@pytest.mark.security
def test_get_history_404_when_scope_cannot_see(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Anonymous user пытается /history для STAFF статьи → 404."""
    _override_list_versions(monkeypatch, None)
    try:
        # Без токена — guest scope, get_by_slug отсекает STAFF → None.
        response = client.get("/api/v1/articles/staff-article/history")
    finally:
        _cleanup_session_override()
    assert response.status_code == 404


def test_get_history_empty_array_when_no_versions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge case: статья видна, но версий нет (defensive — не должно
    случиться в нормальном flow). 200 + пустой массив."""
    _override_list_versions(monkeypatch, [])
    try:
        response = client.get("/api/v1/articles/edge/history")
    finally:
        _cleanup_session_override()
    assert response.status_code == 200
    assert response.json() == {"data": []}


# ============================================================
# PATCH /api/v1/articles/{slug} (E4.5 #38)
# ============================================================


def _override_patch(
    monkeypatch: pytest.MonkeyPatch,
    return_value: tuple[Article, str, str] | None,
    capture: dict[str, Any] | None = None,
) -> None:
    """Подменяет ArticleRepository.patch."""

    async def _fake(
        self: Any,
        slug: str,
        payload: Any,
        access_levels: frozenset[Any],
        *,
        actor_sub: str,
    ) -> tuple[Article, str, str] | None:
        if capture is not None:
            capture["slug"] = slug
            capture["actor_sub"] = actor_sub
            capture["payload"] = payload
        return return_value

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.patch", _fake)

    from src.api.db import get_session
    from src.api.main import app

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session


def test_patch_articles_401_without_token(client: TestClient) -> None:
    response = client.patch("/api/v1/articles/slug", json={"title": "x"})
    assert response.status_code == 401


def test_patch_articles_403_when_tenant_scope(
    client: TestClient, make_jwt: Callable[..., str]
) -> None:
    token = make_jwt(roles=["tenant"])
    response = client.patch(
        "/api/v1/articles/slug",
        json={"title": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_patch_articles_200_updates_title(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    fake_article.title = "New Title"
    _override_patch(monkeypatch, (fake_article, "PUBLIC", "PUBLISHED"))
    try:
        token = make_jwt(roles=["staff_admin"], sub="admin-user")
        response = client.patch(
            "/api/v1/articles/some-slug",
            json={"title": "New Title"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "New Title"


def test_patch_articles_404_when_article_not_found(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _override_patch(monkeypatch, None)
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.patch(
            "/api/v1/articles/missing",
            json={"title": "x"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 404


@pytest.mark.security
@pytest.mark.parametrize(
    "forbidden_field",
    [
        "access_level",
        "slug",
        "category",
        "audience",
        "language",
        "short_answer",
    ],
)
def test_patch_articles_422_when_forbidden_field_in_payload(
    client: TestClient,
    make_jwt: Callable[..., str],
    forbidden_field: str,
) -> None:
    """`extra='forbid'`: попытка передать запрещённое поле → 422.

    Особо `access_level` — security: блокирует тихую эскалацию visibility
    через PATCH (только PUT с явным target check может менять access_level).
    """
    token = make_jwt(roles=["staff_admin"])
    response = client.patch(
        "/api/v1/articles/slug",
        json={"title": "x", forbidden_field: "PUBLIC"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_patch_articles_empty_payload_returns_200(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    """Empty `{}` — 200 no-op (repository не создаёт версию)."""
    _override_patch(monkeypatch, (fake_article, "PUBLIC", "PUBLISHED"))
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.patch(
            "/api/v1/articles/slug",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 200


def test_patch_articles_audit_log_emitted_without_content(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ФЗ-152: PATCH использует `log_article_updated` (как PUT) — без content."""
    import logging

    fake_article.status = "PUBLISHED"
    _override_patch(monkeypatch, (fake_article, "PUBLIC", "DRAFT"))
    try:
        token = make_jwt(roles=["staff_admin"], sub="actor")
        caplog.set_level(logging.INFO, logger="rehome.kb.audit")
        response = client.patch(
            "/api/v1/articles/slug",
            json={"status": "PUBLISHED"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 200
    audit_records = [r for r in caplog.records if r.name == "rehome.kb.audit"]
    assert len(audit_records) == 1
    rec = audit_records[0]
    assert rec.getMessage() == "articles.updated"
    assert getattr(rec, "actor_sub", None) == "actor"
    assert getattr(rec, "old_status", None) == "DRAFT"
    assert getattr(rec, "new_status", None) == "PUBLISHED"
    for attr in ("body_markdown", "title", "summary", "short_answer"):
        assert not hasattr(rec, attr)


def test_patch_articles_actor_sub_from_jwt_not_payload(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    capture: dict[str, Any] = {}
    _override_patch(monkeypatch, (fake_article, "PUBLIC", "PUBLISHED"), capture)
    try:
        token = make_jwt(roles=["staff_admin"], sub="real-actor")
        # Попытка передать actor_sub в payload отвергается `extra='forbid'`.
        response = client.patch(
            "/api/v1/articles/slug",
            json={"title": "x", "actor_sub": "spoofed"},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 422


# ============================================================
# POST /api/v1/articles/search — Postgres FTS (E2.5a #46)
# ============================================================


def _override_search(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[tuple[Any, ...]],
    has_more: bool = False,
    capture: dict[str, Any] | None = None,
) -> None:
    """Подменяет ArticleRepository.search."""

    async def _fake(
        self: Any,
        q: str,
        access_levels: frozenset[Any],
        *,
        cursor: Any = None,
        limit: int = 10,
    ) -> tuple[list[Any], bool]:
        if capture is not None:
            capture["q"] = q
            capture["access_levels"] = access_levels
            capture["cursor"] = cursor
            capture["limit"] = limit
        return rows, has_more

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.search", _fake)

    from src.api.db import get_session
    from src.api.main import app

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session


def test_search_returns_200_with_data(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        (uuid4(), "Договор аренды", "<b>Договор</b> аренды...", 0.85),
        (uuid4(), "Другой документ", "...<b>договор</b>...", 0.42),
    ]
    _override_search(monkeypatch, rows)
    try:
        response = client.post("/api/v1/articles/search", json={"q": "договор"})
    finally:
        _cleanup_session_override()
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["data"]) == 2
    assert body["data"][0]["type"] == "article"
    assert body["data"][0]["title"] == "Договор аренды"
    assert body["data"][0]["score"] == 0.85
    assert "<b>" in body["data"][0]["snippet"]


def test_search_empty_q_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/articles/search", json={"q": ""})
    assert response.status_code == 422


def test_search_whitespace_only_q_returns_422(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _override_search(monkeypatch, [])
    try:
        response = client.post("/api/v1/articles/search", json={"q": "   "})
    finally:
        _cleanup_session_override()
    assert response.status_code == 422


def test_search_q_too_long_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/articles/search", json={"q": "x" * 501})
    assert response.status_code == 422


def test_search_limit_out_of_range_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/articles/search", json={"q": "x", "limit": 51})
    assert response.status_code == 422


def test_search_score_clipped_to_one(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ts_rank теоретически > 1; router clip'ит к 1.0."""
    rows = [(uuid4(), "T", "snip", 1.5)]  # > 1
    _override_search(monkeypatch, rows)
    try:
        response = client.post("/api/v1/articles/search", json={"q": "x"})
    finally:
        _cleanup_session_override()
    assert response.status_code == 200
    assert response.json()["data"][0]["score"] == 1.0


def test_search_returns_cursor_when_has_more(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [(uuid4(), "T", "s", 0.5)]
    _override_search(monkeypatch, rows, has_more=True)
    try:
        response = client.post("/api/v1/articles/search", json={"q": "x", "limit": 1})
    finally:
        _cleanup_session_override()
    body = response.json()
    assert body["pagination"]["has_more"] is True
    assert isinstance(body["pagination"]["cursor_next"], str)
    assert len(body["pagination"]["cursor_next"]) > 0


def test_search_invalid_cursor_returns_400(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _override_search(monkeypatch, [])
    try:
        response = client.post(
            "/api/v1/articles/search",
            json={"q": "x", "cursor": "это-не-base64-©®"},
        )
    finally:
        _cleanup_session_override()
    assert response.status_code == 400


def test_search_passes_access_levels_from_dependency(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_search(monkeypatch, [], capture=capture)
    try:
        # Без токена → guest → access_levels = {PUBLIC}.
        client.post("/api/v1/articles/search", json={"q": "x"})
    finally:
        _cleanup_session_override()
    assert {lvl.value for lvl in capture["access_levels"]} == {"PUBLIC"}


def test_search_default_limit_is_10(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture: dict[str, Any] = {}
    _override_search(monkeypatch, [], capture=capture)
    try:
        client.post("/api/v1/articles/search", json={"q": "x"})
    finally:
        _cleanup_session_override()
    assert capture["limit"] == 10


def test_search_extra_field_rejected(client: TestClient) -> None:
    """`extra='forbid'` — unknown поля → 422."""
    response = client.post("/api/v1/articles/search", json={"q": "x", "random": "field"})
    assert response.status_code == 422


# ============================================================
# ETag + If-None-Match + If-Match (E5.2 #48)
# ============================================================


def test_get_article_returns_etag_and_cache_headers(
    client: TestClient,
    override_session: Callable[[Article | None], None],
    fake_article: Article,
) -> None:
    override_session(fake_article)
    response = client.get(f"/api/v1/articles/{fake_article.slug}")
    assert response.status_code == 200
    assert response.headers["ETag"].startswith('W/"')
    assert response.headers["Cache-Control"] == "public, max-age=60"
    # Vary: Authorization — B1 plan-review (RFC 7234 §4.1).
    assert response.headers["Vary"] == "Authorization"


def test_get_article_if_none_match_returns_304(
    client: TestClient,
    override_session: Callable[[Article | None], None],
    fake_article: Article,
) -> None:
    override_session(fake_article)
    # First request — capture ETag.
    first = client.get(f"/api/v1/articles/{fake_article.slug}")
    etag = first.headers["ETag"]
    # Second request — same ETag.
    override_session(fake_article)
    second = client.get(
        f"/api/v1/articles/{fake_article.slug}",
        headers={"If-None-Match": etag},
    )
    assert second.status_code == 304
    # 304 body — пустой.
    assert second.content == b""
    # ETag и Cache-Control должны быть в 304 response.
    assert second.headers["ETag"] == etag
    assert second.headers["Cache-Control"] == "public, max-age=60"
    assert second.headers["Vary"] == "Authorization"


def test_get_article_if_none_match_mismatch_returns_200(
    client: TestClient,
    override_session: Callable[[Article | None], None],
    fake_article: Article,
) -> None:
    override_session(fake_article)
    response = client.get(
        f"/api/v1/articles/{fake_article.slug}",
        headers={"If-None-Match": 'W/"stale"'},
    )
    assert response.status_code == 200
    # Новый ETag присутствует.
    assert response.headers["ETag"] != 'W/"stale"'


def test_put_with_if_match_passes_to_repo(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    """Router передаёт If-Match header → repo.update."""
    captured: dict[str, Any] = {}

    async def _fake(
        self: Any,
        slug: str,
        payload: Any,
        access_levels: Any,
        *,
        actor_sub: str,
        if_match: str | None = None,
    ) -> tuple[Article, str, str] | None:
        captured["if_match"] = if_match
        return fake_article, "PUBLIC", "PUBLISHED"

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.update", _fake)
    from src.api.db import get_session
    from src.api.main import app

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.put(
            "/api/v1/articles/my-slug",
            json={
                "slug": "my-slug",
                "title": "T",
                "body_markdown": "B",
                "category": "c",
                "audience": "tenant",
                "access_level": "PUBLIC",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "If-Match": 'W/"abc123"',
            },
        )
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert response.status_code == 200
    assert captured["if_match"] == 'W/"abc123"'


def test_put_without_if_match_passes_none_to_repo(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
) -> None:
    """Legacy behavior: без If-Match → if_match=None в repo."""
    captured: dict[str, Any] = {}

    async def _fake(
        self: Any,
        slug: str,
        payload: Any,
        access_levels: Any,
        *,
        actor_sub: str,
        if_match: str | None = None,
    ) -> tuple[Article, str, str] | None:
        captured["if_match"] = if_match
        return fake_article, "PUBLIC", "PUBLISHED"

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.update", _fake)
    from src.api.db import get_session
    from src.api.main import app

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session
    try:
        token = make_jwt(roles=["staff_admin"])
        client.put(
            "/api/v1/articles/my-slug",
            json={
                "slug": "my-slug",
                "title": "T",
                "body_markdown": "B",
                "category": "c",
                "audience": "tenant",
                "access_level": "PUBLIC",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert captured["if_match"] is None


def test_put_with_stale_if_match_returns_412(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repo.update raises PreconditionFailedError → router 412."""
    from src.api.articles.repository import PreconditionFailedError

    async def _fake(
        self: Any,
        slug: str,
        payload: Any,
        access_levels: Any,
        *,
        actor_sub: str,
        if_match: str | None = None,
    ) -> tuple[Article, str, str] | None:
        raise PreconditionFailedError

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.update", _fake)
    from src.api.db import get_session
    from src.api.main import app

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.put(
            "/api/v1/articles/my-slug",
            json={
                "slug": "my-slug",
                "title": "T",
                "body_markdown": "B",
                "category": "c",
                "audience": "tenant",
                "access_level": "PUBLIC",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "If-Match": 'W/"stale"',
            },
        )
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert response.status_code == 412


def test_history_returns_etag_and_cache_headers(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from src.api.articles.models import ArticleVersion

    aid = uuid4()
    v1 = ArticleVersion(
        article_id=aid,
        version=1,
        event="CREATE",
        author_sub="x",
        new_status="DRAFT",
        new_access_level="PUBLIC",
    )
    v1.changed_at = datetime(2026, 5, 12, tzinfo=UTC)
    _override_list_versions(monkeypatch, [v1])
    try:
        response = client.get("/api/v1/articles/test-slug/history")
    finally:
        _cleanup_session_override()
    assert response.status_code == 200
    assert response.headers["ETag"].startswith('W/"')
    assert response.headers["Cache-Control"] == "public, max-age=60"
    assert response.headers["Vary"] == "Authorization"


def test_history_if_none_match_returns_304(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from src.api.articles.models import ArticleVersion

    aid = uuid4()
    v1 = ArticleVersion(
        article_id=aid,
        version=1,
        event="CREATE",
        author_sub="x",
        new_status="DRAFT",
        new_access_level="PUBLIC",
    )
    v1.changed_at = datetime(2026, 5, 12, tzinfo=UTC)
    _override_list_versions(monkeypatch, [v1])
    try:
        first = client.get("/api/v1/articles/test/history")
        etag = first.headers["ETag"]
        _override_list_versions(monkeypatch, [v1])
        second = client.get(
            "/api/v1/articles/test/history",
            headers={"If-None-Match": etag},
        )
    finally:
        _cleanup_session_override()
    assert second.status_code == 304
    assert second.content == b""
