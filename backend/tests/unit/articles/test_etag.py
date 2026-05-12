"""Tests для ETag helpers (E5.2 #48)."""

from datetime import UTC, datetime
from uuid import uuid4

from src.api.articles.etag import (
    DEFAULT_CACHE_HEADERS,
    compute_article_etag,
    compute_history_etag,
)
from src.api.articles.models import Article, ArticleVersion


def _make_article() -> Article:
    a = Article()
    a.id = uuid4()
    a.slug = "test"
    a.title = "T"
    a.body_markdown = "b"
    a.audience = "tenant"
    a.language = "ru"
    a.category = "c"
    a.tags = []
    a.access_level = "PUBLIC"
    a.status = "PUBLISHED"
    a.published_at = None
    a.created_at = datetime(2026, 5, 12, tzinfo=UTC)
    a.updated_at = datetime(2026, 5, 12, tzinfo=UTC)
    return a


def test_etag_is_weak_format() -> None:
    a = _make_article()
    etag = compute_article_etag(a)
    assert etag.startswith('W/"')
    assert etag.endswith('"')
    # 16 hex chars + W/" + closing "
    assert len(etag) == len('W/"') + 16 + 1


def test_etag_deterministic() -> None:
    a = _make_article()
    assert compute_article_etag(a) == compute_article_etag(a)


def test_etag_changes_on_updated_at() -> None:
    a = _make_article()
    e1 = compute_article_etag(a)
    a.updated_at = datetime(2026, 5, 13, tzinfo=UTC)
    e2 = compute_article_etag(a)
    assert e1 != e2


def test_etag_changes_on_access_level() -> None:
    a = _make_article()
    e1 = compute_article_etag(a)
    a.access_level = "STAFF"
    e2 = compute_article_etag(a)
    assert e1 != e2


def test_etag_changes_on_status() -> None:
    a = _make_article()
    e1 = compute_article_etag(a)
    a.status = "DRAFT"
    e2 = compute_article_etag(a)
    assert e1 != e2


def test_etag_changes_on_id() -> None:
    a = _make_article()
    e1 = compute_article_etag(a)
    a.id = uuid4()
    e2 = compute_article_etag(a)
    assert e1 != e2


def test_default_cache_headers() -> None:
    """Vary: Authorization обязателен (per B1 plan-review)."""
    assert DEFAULT_CACHE_HEADERS["Cache-Control"] == "public, max-age=60"
    assert DEFAULT_CACHE_HEADERS["Vary"] == "Authorization"


def test_history_etag_empty_versions() -> None:
    assert compute_history_etag([]) == 'W/"empty"'


def _make_version(version: int, changed_at: datetime) -> ArticleVersion:
    v = ArticleVersion()
    v.article_id = uuid4()
    v.version = version
    v.event = "UPDATE"
    v.author_sub = "actor"
    v.changed_at = changed_at
    v.new_status = "PUBLISHED"
    v.new_access_level = "PUBLIC"
    return v


def test_history_etag_uses_max_version() -> None:
    aid = uuid4()
    v1 = _make_version(1, datetime(2026, 5, 10, tzinfo=UTC))
    v2 = _make_version(2, datetime(2026, 5, 11, tzinfo=UTC))
    v1.article_id = v2.article_id = aid
    # DESC order — v2 first.
    e1 = compute_history_etag([v2, v1])
    # Изменение в v1 (не последняя версия) не должно менять etag.
    v1.changed_at = datetime(2026, 5, 9, tzinfo=UTC)
    e2 = compute_history_etag([v2, v1])
    assert e1 == e2


def test_history_etag_changes_when_max_version_increments() -> None:
    aid = uuid4()
    v1 = _make_version(1, datetime(2026, 5, 10, tzinfo=UTC))
    v2 = _make_version(2, datetime(2026, 5, 11, tzinfo=UTC))
    v3 = _make_version(3, datetime(2026, 5, 12, tzinfo=UTC))
    v1.article_id = v2.article_id = v3.article_id = aid

    e1 = compute_history_etag([v2, v1])
    e2 = compute_history_etag([v3, v2, v1])
    assert e1 != e2
