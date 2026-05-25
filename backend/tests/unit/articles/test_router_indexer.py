"""E2E test that `RAG_ENABLED=True` triggers IndexerService from article router (#130)."""

from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.articles.models import Article
from src.api.db import get_session
from src.api.main import app
from src.api.search.indexer import IndexerService, get_indexer_service


@pytest.fixture
def indexer_mock() -> Iterator[MagicMock]:
    """Overrides global no-op indexer with tracking AsyncMock."""
    fake = MagicMock(spec=IndexerService)
    fake.index_article = AsyncMock(return_value=1)
    fake.remove_article = AsyncMock(return_value=0)
    fake.remove_article_by_slug = AsyncMock(return_value=0)
    app.dependency_overrides[get_indexer_service] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_indexer_service, None)


def _override_create(monkeypatch: pytest.MonkeyPatch, fake_article: Article) -> None:
    async def _fake(self: Any, payload: Any, *, actor_sub: str) -> Article:
        fake_article.slug = payload.slug
        fake_article.title = payload.title
        fake_article.body_markdown = payload.body_markdown
        fake_article.category = payload.category
        fake_article.audience = payload.audience
        fake_article.access_level = payload.access_level.value
        fake_article.status = payload.status
        fake_article.language = payload.language
        fake_article.tags = list(payload.tags)
        return fake_article

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create", _fake)
    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create_atomic", _fake)

    async def _empty_session() -> Any:
        from unittest.mock import AsyncMock, MagicMock
        _sess = MagicMock()
        _sess.commit = AsyncMock()
        _sess.rollback = AsyncMock()
        _sess.refresh = AsyncMock()
        _sess.add = MagicMock()
        _sess.flush = AsyncMock()
        yield _sess

    app.dependency_overrides[get_session] = _empty_session


def _post_body(status_: str = "PUBLISHED") -> dict[str, Any]:
    return {
        "slug": "rag-test",
        "title": "RAG test",
        "body_markdown": "Para A.\n\nPara B.",
        "category": "rental",
        "audience": "tenant",
        "language": "ru",
        "access_level": "PUBLIC",
        "status": status_,
        "tags": [],
    }


def test_post_published_triggers_index_when_rag_enabled(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    indexer_mock: MagicMock,
) -> None:
    """RAG_ENABLED=True + POST PUBLISHED → indexer.index_article called."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    fake_article.status = "PUBLISHED"
    _override_create(monkeypatch, fake_article)

    token = make_jwt(roles=["staff_admin"])
    resp = client.post(
        "/api/v1/articles",
        json=_post_body("PUBLISHED"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    indexer_mock.index_article.assert_awaited_once()
    kwargs = indexer_mock.index_article.call_args.kwargs
    # body_markdown берётся из article (override_create копирует из payload).
    assert kwargs["body_markdown"] == _post_body()["body_markdown"]
    assert kwargs["article_id"] == fake_article.id


def test_post_draft_triggers_remove_when_rag_enabled(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    indexer_mock: MagicMock,
) -> None:
    """RAG_ENABLED=True + POST DRAFT → remove_article (cleanup-if-was-published)."""
    monkeypatch.setenv("RAG_ENABLED", "true")
    fake_article.status = "DRAFT"
    _override_create(monkeypatch, fake_article)

    token = make_jwt(roles=["staff_admin"])
    resp = client.post(
        "/api/v1/articles",
        json=_post_body("DRAFT"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    indexer_mock.remove_article.assert_awaited_once()
    indexer_mock.index_article.assert_not_awaited()


def test_post_published_no_op_when_rag_disabled(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    indexer_mock: MagicMock,
) -> None:
    """Default RAG_ENABLED=False → indexer не called."""
    monkeypatch.delenv("RAG_ENABLED", raising=False)
    fake_article.status = "PUBLISHED"
    _override_create(monkeypatch, fake_article)

    token = make_jwt(roles=["staff_admin"])
    resp = client.post(
        "/api/v1/articles",
        json=_post_body("PUBLISHED"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    indexer_mock.index_article.assert_not_awaited()
    indexer_mock.remove_article.assert_not_awaited()


def test_delete_archives_and_removes_by_slug_when_rag_enabled(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    indexer_mock: MagicMock,
) -> None:
    monkeypatch.setenv("RAG_ENABLED", "true")

    async def _fake_archive(
        self: Any, slug: str, levels: Any, *, actor_sub: str
    ) -> tuple[str, str]:
        return ("PUBLISHED", "PUBLIC")

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.archive", _fake_archive)

    async def _empty_session() -> Any:
        from unittest.mock import AsyncMock, MagicMock
        _sess = MagicMock()
        _sess.commit = AsyncMock()
        _sess.rollback = AsyncMock()
        _sess.refresh = AsyncMock()
        _sess.add = MagicMock()
        _sess.flush = AsyncMock()
        yield _sess

    app.dependency_overrides[get_session] = _empty_session
    try:
        token = make_jwt(roles=["staff_admin"])
        resp = client.delete(
            "/api/v1/articles/the-slug",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204
        indexer_mock.remove_article_by_slug.assert_awaited_once_with("the-slug")
    finally:
        app.dependency_overrides.pop(get_session, None)
