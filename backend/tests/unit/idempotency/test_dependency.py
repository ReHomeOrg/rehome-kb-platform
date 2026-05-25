"""Unit-тесты dependency `process_idempotency_key` (E5.1 #44)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.idempotency.models import IdempotencyKey
from src.api.idempotency.repository import (
    IdempotencyKeyRepository,
    get_idempotency_repository,
)
from src.api.main import app


def _make_fake_repo() -> Any:
    """Mock IdempotencyKeyRepository c трекингом вызовов."""
    repo = MagicMock(spec=IdempotencyKeyRepository)
    repo.acquire_lock = AsyncMock()
    repo.get = AsyncMock(return_value=None)
    repo.save = AsyncMock()
    return repo


def _override_idempotency_repo(repo: Any) -> Callable[[], None]:
    """Подменяет get_idempotency_repository dependency."""

    def _get_fake() -> Any:
        return repo

    app.dependency_overrides[get_idempotency_repository] = _get_fake

    def _cleanup() -> None:
        app.dependency_overrides.pop(get_idempotency_repository, None)

    return _cleanup


def test_post_without_idempotency_key_is_noop(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без header — `process_idempotency_key` НЕ обращается к repo."""
    repo = _make_fake_repo()
    cleanup = _override_idempotency_repo(repo)

    # Подмена article create — fake article.
    from src.api.articles.models import Article

    article = Article()
    article.id = uuid4()
    article.slug = "noop"
    article.title = "T"
    article.body_markdown = "B"
    article.category = "c"
    article.audience = "tenant"
    article.access_level = "PUBLIC"
    article.status = "DRAFT"
    article.language = "ru"
    article.tags = []
    article.published_at = None
    article.created_at = datetime.now(UTC)
    article.updated_at = datetime.now(UTC)

    async def _fake_create(self: Any, payload: Any, *, actor_sub: str) -> Article:
        return article

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create", _fake_create)
    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create_atomic", _fake_create)

    from src.api.db import get_session

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
        response = client.post(
            "/api/v1/articles",
            json={
                "slug": "noop",
                "title": "T",
                "body_markdown": "B",
                "category": "c",
                "audience": "tenant",
                "access_level": "PUBLIC",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        cleanup()
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 201
    # Без key — repo.get / acquire_lock / save НЕ вызываются.
    repo.get.assert_not_awaited()
    repo.acquire_lock.assert_not_awaited()
    repo.save.assert_not_awaited()


def test_post_with_invalid_idempotency_key_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
) -> None:
    """Не-UUID Idempotency-Key → 422."""
    repo = _make_fake_repo()
    cleanup = _override_idempotency_repo(repo)
    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.post(
            "/api/v1/articles",
            json={
                "slug": "x",
                "title": "T",
                "body_markdown": "B",
                "category": "c",
                "audience": "tenant",
                "access_level": "PUBLIC",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "not-a-uuid",
            },
        )
    finally:
        cleanup()
    assert response.status_code == 422
    assert "uuid" in response.json()["detail"].lower()


def test_post_with_idempotency_key_first_call_creates_and_saves(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _make_fake_repo()
    repo.get = AsyncMock(return_value=None)  # cache empty
    cleanup = _override_idempotency_repo(repo)

    from src.api.articles.models import Article

    article = Article()
    article.id = uuid4()
    article.slug = "first"
    article.title = "T"
    article.body_markdown = "B"
    article.category = "c"
    article.audience = "tenant"
    article.access_level = "PUBLIC"
    article.status = "DRAFT"
    article.language = "ru"
    article.tags = []
    article.published_at = None
    article.created_at = datetime.now(UTC)
    article.updated_at = datetime.now(UTC)

    async def _fake_create(self: Any, payload: Any, *, actor_sub: str) -> Article:
        return article

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create", _fake_create)
    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create_atomic", _fake_create)

    from src.api.db import get_session

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
        key = str(uuid4())
        token = make_jwt(roles=["staff_admin"])
        response = client.post(
            "/api/v1/articles",
            json={
                "slug": "first",
                "title": "T",
                "body_markdown": "B",
                "category": "c",
                "audience": "tenant",
                "access_level": "PUBLIC",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": key,
            },
        )
    finally:
        cleanup()
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 201
    # Lock и lookup были вызваны.
    repo.acquire_lock.assert_awaited_once()
    repo.get.assert_awaited_once()
    # И save после execution.
    repo.save.assert_awaited_once()


def test_post_with_idempotency_key_replay_returns_cached_response(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry с тем же key + body → replay (без execute create)."""
    from hashlib import sha256

    payload = {
        "slug": "replay",
        "title": "Old Title",
        "body_markdown": "Old",
        "category": "c",
        "audience": "tenant",
        "access_level": "PUBLIC",
    }
    # Body hash — нужно симулировать exact same bytes как client отправит.
    import json

    body_bytes = json.dumps(payload).encode()
    body_hash = sha256(body_bytes).hexdigest()

    cached_response = {"id": "cached-id", "slug": "replay", "title": "Old Title"}
    cached_entry = IdempotencyKey(
        key=str(uuid4()),
        request_path="/api/v1/articles",
        actor_sub="test-user-uuid",
        request_body_hash=body_hash,
        response_status=201,
        response_body=cached_response,
        response_headers={"Location": "/api/v1/articles/replay"},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    repo = _make_fake_repo()
    repo.get = AsyncMock(return_value=cached_entry)
    cleanup = _override_idempotency_repo(repo)

    create_called = [False]

    async def _fake_create(self: Any, p: Any, *, actor_sub: str) -> Any:
        create_called[0] = True
        return None  # should NOT be called

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create", _fake_create)
    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create_atomic", _fake_create)

    from src.api.db import get_session

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
        response = client.post(
            "/api/v1/articles",
            content=body_bytes,  # Точные bytes как для hash.
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": cached_entry.key,
                "Content-Type": "application/json",
            },
        )
    finally:
        cleanup()
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 201
    # Replay — body совпадает с cached.
    assert response.json() == cached_response
    # Create НЕ вызывался.
    assert create_called[0] is False
    # Save НЕ вызывался (replay path).
    repo.save.assert_not_awaited()


@pytest.mark.security
def test_post_with_same_key_different_body_returns_409(
    client: TestClient,
    make_jwt: Callable[..., str],
) -> None:
    """Retry с тем же key но другим body → 409."""
    cached_entry = IdempotencyKey(
        key=str(uuid4()),
        request_path="/api/v1/articles",
        actor_sub="test-user-uuid",
        request_body_hash="different-hash-than-current-request",
        response_status=201,
        response_body={"x": "y"},
        response_headers={},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    repo = _make_fake_repo()
    repo.get = AsyncMock(return_value=cached_entry)
    cleanup = _override_idempotency_repo(repo)

    try:
        token = make_jwt(roles=["staff_admin"])
        response = client.post(
            "/api/v1/articles",
            json={
                "slug": "conflict",
                "title": "T",
                "body_markdown": "B",
                "category": "c",
                "audience": "tenant",
                "access_level": "PUBLIC",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": cached_entry.key,
            },
        )
    finally:
        cleanup()
    assert response.status_code == 409
    assert "different request body" in response.json()["detail"].lower()


@pytest.mark.security
def test_lock_acquired_before_lookup(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2: lock FIRST, потом lookup. Order закрывает race window."""
    calls: list[str] = []

    repo = MagicMock(spec=IdempotencyKeyRepository)

    async def _lock(key: str, path: str, actor_sub: str) -> None:
        calls.append("lock")

    async def _get(key: str, path: str, actor_sub: str) -> None:
        calls.append("get")
        return

    repo.acquire_lock = _lock
    repo.get = _get
    repo.save = AsyncMock()
    cleanup = _override_idempotency_repo(repo)

    from src.api.articles.models import Article

    article = Article()
    article.id = uuid4()
    article.slug = "lock-test"
    article.title = "T"
    article.body_markdown = "B"
    article.category = "c"
    article.audience = "tenant"
    article.access_level = "PUBLIC"
    article.status = "DRAFT"
    article.language = "ru"
    article.tags = []
    article.published_at = None
    article.created_at = datetime.now(UTC)
    article.updated_at = datetime.now(UTC)

    async def _fake_create(self: Any, p: Any, *, actor_sub: str) -> Article:
        return article

    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create", _fake_create)
    monkeypatch.setattr("src.api.articles.router.ArticleRepository.create_atomic", _fake_create)

    from src.api.db import get_session

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
        client.post(
            "/api/v1/articles",
            json={
                "slug": "lock-test",
                "title": "T",
                "body_markdown": "B",
                "category": "c",
                "audience": "tenant",
                "access_level": "PUBLIC",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": str(uuid4()),
            },
        )
    finally:
        cleanup()
        app.dependency_overrides.pop(get_session, None)

    # Lock — первый, get — второй.
    assert calls == ["lock", "get"]
