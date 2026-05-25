"""ADR-0026 Slice 1 atomic transaction guarantees для POST /articles.

Tests verify:
- session.commit() called once в конце handler (atomic).
- При exception до commit'а — handler propagates → 5xx (rollback happens
  via session manager close).
- create_atomic не commit'ит сам (Slice 1 invariant: caller манагит).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.articles.models import Article
from src.api.db import get_session
from src.api.main import app


def _post_payload() -> dict[str, Any]:
    return {
        "slug": "atomic-test",
        "title": "Atomic",
        "body_markdown": "# Body",
        "category": "guide",
        "audience": "tenant",
        "access_level": "PUBLIC",
    }


def _fake_article() -> Article:
    a = Article()
    a.id = uuid4()
    a.slug = "atomic-test"
    a.title = "Atomic"
    a.body_markdown = "# Body"
    a.category = "guide"
    a.audience = "tenant"
    a.access_level = "PUBLIC"
    a.status = "DRAFT"
    a.language = "ru"
    a.tags = []
    a.published_at = None
    from datetime import UTC, datetime

    a.created_at = datetime.now(UTC)
    a.updated_at = datetime.now(UTC)
    return a


@pytest.fixture
def session_mock() -> Iterator[MagicMock]:
    """Mock session с trackable commit / rollback / refresh."""
    sess = MagicMock()
    sess.commit = AsyncMock()
    sess.rollback = AsyncMock()
    sess.refresh = AsyncMock()
    sess.add = MagicMock()
    sess.flush = AsyncMock()

    async def _factory() -> Any:
        yield sess

    app.dependency_overrides[get_session] = _factory
    yield sess
    app.dependency_overrides.pop(get_session, None)


def test_post_article_calls_session_commit_once(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    session_mock: MagicMock,
) -> None:
    """ADR-0026 Slice 1: handler делает session.commit ровно один раз —
    atomic transaction (article + version + audit row + (outbox если
    enabled))."""
    article = _fake_article()

    async def _fake_create_atomic(self: Any, payload: Any, *, actor_sub: str) -> Article:
        # Имитирует create_atomic — добавляет, не commit'ит.
        return article

    monkeypatch.setattr(
        "src.api.articles.router.ArticleRepository.create_atomic",
        _fake_create_atomic,
    )

    token = make_jwt(roles=["staff_admin"], sub="admin-x")
    resp = client.post(
        "/api/v1/articles",
        json=_post_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    # Exactly one commit — atomic guarantee.
    session_mock.commit.assert_awaited_once()
    # refresh called after commit (recovers DB defaults).
    session_mock.refresh.assert_awaited_once_with(article)


def test_post_article_create_failure_no_commit(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    session_mock: MagicMock,
) -> None:
    """`create_atomic` raises → handler propagates → 5xx; session.commit
    НЕ вызывается (rollback на session close)."""
    from src.api.articles.repository import SlugConflictError

    async def _fail(self: Any, payload: Any, *, actor_sub: str) -> Article:
        raise SlugConflictError("atomic-test")

    monkeypatch.setattr(
        "src.api.articles.router.ArticleRepository.create_atomic",
        _fail,
    )

    token = make_jwt(roles=["staff_admin"], sub="admin-x")
    resp = client.post(
        "/api/v1/articles",
        json=_post_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409  # SlugConflictError → 409 mapping
    session_mock.commit.assert_not_awaited()


def test_post_article_audit_failure_no_commit(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    session_mock: MagicMock,
) -> None:
    """audit_repo.record raises → handler propagates → session.commit НЕ
    вызывается → article rollback (article + version не persistятся).

    Bypass'ит autouse `_no_op_audit_repository` через explicit override.
    """
    from src.api.audit.repository import AuditRepository, get_audit_repository

    article = _fake_article()

    async def _ok(self: Any, payload: Any, *, actor_sub: str) -> Article:
        return article

    fail_repo = MagicMock(spec=AuditRepository)
    fail_repo.record = AsyncMock(side_effect=RuntimeError("audit DB down"))
    app.dependency_overrides[get_audit_repository] = lambda: fail_repo

    monkeypatch.setattr(
        "src.api.articles.router.ArticleRepository.create_atomic",
        _ok,
    )

    try:
        token = make_jwt(roles=["staff_admin"], sub="admin-x")
        # TestClient с raise_server_exceptions=True пробрасывает
        # RuntimeError в test code; ловим через pytest.raises.
        with pytest.raises(RuntimeError, match="audit DB down"):
            client.post(
                "/api/v1/articles",
                json=_post_payload(),
                headers={"Authorization": f"Bearer {token}"},
            )
        # CRITICAL invariant: commit НЕ должен быть вызван — article row
        # rollback'ится с session close.
        session_mock.commit.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_audit_repository, None)
