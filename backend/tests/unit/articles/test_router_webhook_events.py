"""E5.3 #91: verify article router fires webhook events on status transitions."""

from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.articles.models import Article
from src.api.db import get_session
from src.api.main import app
from src.api.webhooks.dispatcher import (
    WebhookEventDispatcher,
    get_webhook_event_dispatcher,
)


@pytest.fixture
def dispatch_mock() -> Iterator[AsyncMock]:
    """Overrides global no-op dispatcher with one we can assert on."""
    dispatch = AsyncMock(return_value=1)
    fake_dispatcher = MagicMock(spec=WebhookEventDispatcher)
    fake_dispatcher.dispatch = dispatch
    app.dependency_overrides[get_webhook_event_dispatcher] = lambda: fake_dispatcher
    yield dispatch
    app.dependency_overrides.pop(get_webhook_event_dispatcher, None)


def _override_create(monkeypatch: pytest.MonkeyPatch, article: Article) -> None:
    async def _fake(self: Any, payload: Any, *, actor_sub: str) -> Article:
        article.slug = payload.slug
        article.title = payload.title
        article.body_markdown = payload.body_markdown
        article.category = payload.category
        article.audience = payload.audience
        article.access_level = payload.access_level.value
        article.status = payload.status
        article.language = payload.language
        article.tags = list(payload.tags)
        return article

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create", _fake)

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session


def _override_patch(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    async def _fake(self: Any, slug: str, payload: Any, levels: Any, *, actor_sub: str) -> Any:
        return result

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.patch", _fake)

    async def _empty_session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = _empty_session


def _post_body(status_: str = "PUBLISHED") -> dict[str, Any]:
    return {
        "slug": "test-slug",
        "title": "Title",
        "body_markdown": "Body",
        "category": "rental",
        "audience": "tenant",
        "language": "ru",
        "access_level": "PUBLIC",
        "status": status_,
        "tags": [],
    }


# ---------------------------------------------------------------------------
# POST /articles


def test_post_published_fires_article_published(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    dispatch_mock: AsyncMock,
) -> None:
    fake_article.status = "PUBLISHED"
    _override_create(monkeypatch, fake_article)

    token = make_jwt(roles=["staff_admin"])
    resp = client.post(
        "/api/v1/articles",
        json=_post_body("PUBLISHED"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    dispatch_mock.assert_awaited_once()
    kwargs = dispatch_mock.call_args.kwargs
    assert kwargs["event_type"] == "article.published"
    assert kwargs["payload"]["slug"] == "test-slug"


def test_post_draft_does_not_fire(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    dispatch_mock: AsyncMock,
) -> None:
    fake_article.status = "DRAFT"
    _override_create(monkeypatch, fake_article)

    token = make_jwt(roles=["staff_admin"])
    resp = client.post(
        "/api/v1/articles",
        json=_post_body("DRAFT"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    dispatch_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# PATCH /articles/{slug}


def test_patch_draft_to_published_fires_article_published(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    dispatch_mock: AsyncMock,
) -> None:
    fake_article.status = "PUBLISHED"
    _override_patch(monkeypatch, (fake_article, "PUBLIC", "DRAFT"))

    token = make_jwt(roles=["staff_admin"])
    resp = client.patch(
        f"/api/v1/articles/{fake_article.slug}",
        json={"status": "PUBLISHED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    dispatch_mock.assert_awaited_once()
    assert dispatch_mock.call_args.kwargs["event_type"] == "article.published"


def test_patch_published_to_archived_fires_article_archived(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    dispatch_mock: AsyncMock,
) -> None:
    fake_article.status = "ARCHIVED"
    _override_patch(monkeypatch, (fake_article, "PUBLIC", "PUBLISHED"))

    token = make_jwt(roles=["staff_admin"])
    resp = client.patch(
        f"/api/v1/articles/{fake_article.slug}",
        json={"status": "ARCHIVED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    dispatch_mock.assert_awaited_once()
    assert dispatch_mock.call_args.kwargs["event_type"] == "article.archived"


def test_patch_no_status_change_does_not_fire(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    dispatch_mock: AsyncMock,
) -> None:
    fake_article.status = "PUBLISHED"
    _override_patch(monkeypatch, (fake_article, "PUBLIC", "PUBLISHED"))

    token = make_jwt(roles=["staff_admin"])
    resp = client.patch(
        f"/api/v1/articles/{fake_article.slug}",
        json={"title": "New title"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    # Old status == new status → no event (article.updated out of scope).
    dispatch_mock.assert_not_awaited()
