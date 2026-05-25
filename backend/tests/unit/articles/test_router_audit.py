"""E4.x #102: verify article router writes audit_log rows for write-операций."""

from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.articles.models import Article
from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.db import get_session
from src.api.main import app


@pytest.fixture
def audit_mock() -> Iterator[AsyncMock]:
    """Override the autouse no-op with a tracking AsyncMock."""
    record = AsyncMock()
    fake = MagicMock(spec=AuditRepository)
    fake.record = record
    app.dependency_overrides[get_audit_repository] = lambda: fake
    yield record
    app.dependency_overrides.pop(get_audit_repository, None)


def _override_session() -> None:
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


def _override_create(monkeypatch: pytest.MonkeyPatch, fake_article: Article) -> None:
    async def _fake(self: Any, payload: Any, *, actor_sub: str) -> Article:
        fake_article.slug = payload.slug
        fake_article.access_level = payload.access_level.value
        fake_article.status = payload.status
        return fake_article

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create", _fake)
    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create_atomic", _fake)
    _override_session()


def _override_patch(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    async def _fake(self: Any, slug: str, payload: Any, levels: Any, *, actor_sub: str) -> Any:
        return result

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.patch", _fake)
    _override_session()


def _override_update(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    async def _fake(
        self: Any,
        slug: str,
        payload: Any,
        levels: Any,
        *,
        actor_sub: str,
        if_match: Any = None,
    ) -> Any:
        return result

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.update", _fake)
    _override_session()


def _override_archive(monkeypatch: pytest.MonkeyPatch, result: tuple[str, str] | None) -> None:
    async def _fake(self: Any, slug: str, levels: Any, *, actor_sub: str) -> Any:
        return result

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.archive", _fake)
    _override_session()


def _post_body() -> dict[str, Any]:
    return {
        "slug": "test-slug",
        "title": "Title",
        "body_markdown": "Body",
        "category": "rental",
        "audience": "tenant",
        "language": "ru",
        "access_level": "PUBLIC",
        "status": "DRAFT",
        "tags": [],
    }


# ---------------------------------------------------------------------------
# POST


def test_post_writes_articles_created_audit(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    audit_mock: AsyncMock,
) -> None:
    _override_create(monkeypatch, fake_article)
    token = make_jwt(roles=["staff_admin"], sub="alice-sub")
    resp = client.post(
        "/api/v1/articles",
        json=_post_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["actor_sub"] == "alice-sub"
    assert kwargs["action"] == "articles.created"
    assert kwargs["resource_type"] == "article"
    assert kwargs["resource_id"] == "test-slug"
    assert "access_level" in kwargs["metadata"]


def test_post_does_not_leak_content_in_audit_metadata(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    audit_mock: AsyncMock,
) -> None:
    """ФЗ-152: НЕ должны логировать body_markdown / title в metadata."""
    _override_create(monkeypatch, fake_article)
    token = make_jwt(roles=["staff_admin"], sub="alice-sub")
    client.post(
        "/api/v1/articles",
        json=_post_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    metadata = audit_mock.call_args.kwargs["metadata"]
    assert "body_markdown" not in metadata
    assert "title" not in metadata
    assert "summary" not in metadata


# ---------------------------------------------------------------------------
# PUT


def test_put_writes_articles_updated_with_via_put_marker(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    audit_mock: AsyncMock,
) -> None:
    fake_article.status = "PUBLISHED"
    fake_article.access_level = "PUBLIC"
    _override_update(monkeypatch, (fake_article, "PUBLIC", "DRAFT"))
    token = make_jwt(roles=["staff_admin"], sub="alice-sub")
    body = _post_body()
    body["slug"] = fake_article.slug
    body["status"] = "PUBLISHED"
    resp = client.put(
        f"/api/v1/articles/{fake_article.slug}",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "articles.updated"
    assert kwargs["metadata"]["via"] == "PUT"
    assert kwargs["metadata"]["old_status"] == "DRAFT"
    assert kwargs["metadata"]["new_status"] == "PUBLISHED"


# ---------------------------------------------------------------------------
# PATCH


def test_patch_writes_articles_updated_with_deltas(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    fake_article: Article,
    audit_mock: AsyncMock,
) -> None:
    fake_article.status = "PUBLISHED"
    _override_patch(monkeypatch, (fake_article, "PUBLIC", "DRAFT"))
    token = make_jwt(roles=["staff_admin"], sub="alice-sub")
    resp = client.patch(
        f"/api/v1/articles/{fake_article.slug}",
        json={"status": "PUBLISHED"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "articles.updated"
    md = kwargs["metadata"]
    assert md["old_status"] == "DRAFT"
    assert md["new_status"] == "PUBLISHED"
    assert md["via"] == "PATCH"


# ---------------------------------------------------------------------------
# DELETE


def test_delete_writes_articles_archived(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    audit_mock: AsyncMock,
) -> None:
    _override_archive(monkeypatch, ("PUBLISHED", "PUBLIC"))
    token = make_jwt(roles=["staff_admin"], sub="alice-sub")
    resp = client.delete(
        "/api/v1/articles/some-slug",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "articles.archived"
    assert kwargs["resource_id"] == "some-slug"
    assert kwargs["metadata"]["was_status"] == "PUBLISHED"
    assert kwargs["metadata"]["was_access_level"] == "PUBLIC"


def test_delete_404_does_not_write_audit(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    audit_mock: AsyncMock,
) -> None:
    _override_archive(monkeypatch, None)
    token = make_jwt(roles=["staff_admin"], sub="alice-sub")
    resp = client.delete(
        "/api/v1/articles/nonexistent",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    audit_mock.assert_not_awaited()
