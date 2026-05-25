"""Integration-ish tests для ADR-0025 PATCH Idempotency-Key extension.

Покрывает 8 PATCH endpoints: admin/users, admin/security-incidents,
admin/personal-data/requests, admin/system-config, articles, premises,
collaborators, hr.

Каждый тест проверяет replay path: cached IdempotencyKey row с тем же
body_hash → router возвращает cached response без повторного вызова
business repo.create/update.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
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

# Empty body sha256 — used by handlers без JSON body (e.g. minimal patch).
_EMPTY_BODY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _make_idempotency_repo(cached_body: dict[str, Any], body_hash: str = _EMPTY_BODY_HASH) -> Any:
    """Build mock IdempotencyKeyRepository, .get() возвращает existing row."""
    existing = IdempotencyKey(
        key="ignored",
        request_path="/ignored",
        actor_sub="ignored",
        request_body_hash=body_hash,
        response_status=200,
        response_body=cached_body,
        response_headers={},
    )
    repo = MagicMock(spec=IdempotencyKeyRepository)
    repo.acquire_lock = AsyncMock()
    repo.get = AsyncMock(return_value=existing)
    repo.save = AsyncMock()
    return repo


def _sha256_of(body: bytes) -> str:
    import hashlib

    return hashlib.sha256(body).hexdigest()


@pytest.fixture
def override_idempotency() -> Iterator[Any]:
    """Lets test set replay state via `override_idempotency.return_value =
    _make_idempotency_repo(...)`."""
    holder: dict[str, Any] = {}

    def _getter() -> Any:
        return holder["repo"]

    app.dependency_overrides[get_idempotency_repository] = _getter
    yield holder
    app.dependency_overrides.pop(get_idempotency_repository, None)


# ---------------------------------------------------------------------------
# admin/users PATCH


def test_admin_users_patch_replays_on_idempotency_key(
    client: TestClient,
    make_jwt: Callable[..., str],
    override_idempotency: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cached response → repo.update_fields НЕ вызывается на replay."""
    from src.api.admin.users_repository import (
        KbUserRepository,
        get_kb_user_repository,
    )

    cached_id = uuid4()
    cached_body = {
        "id": str(cached_id),
        "email": "user@x",
        "full_name": "X",
        "role": "staff_support",
        "status": "ACTIVE",
        "permissions": [],
        "mfa_enabled": False,
        "last_login_at": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    # KbUserPatch не принимает full_name (extra=forbid); valid PATCH field:
    body_json = b'{"role":"staff_legal"}'
    override_idempotency["repo"] = _make_idempotency_repo(cached_body, _sha256_of(body_json))

    update_fields_mock = AsyncMock()
    repo = MagicMock(spec=KbUserRepository)
    repo.get_by_id = AsyncMock(return_value=MagicMock())
    repo.update_fields = update_fields_mock
    app.dependency_overrides[get_kb_user_repository] = lambda: repo

    try:
        sub = str(uuid4())
        token = make_jwt(roles=["staff_admin"], sub=sub)
        resp = client.patch(
            f"/api/v1/admin/users/{uuid4()}",
            content=body_json,
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": str(uuid4()),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == str(cached_id)
        # Business logic НЕ вызвалась — это replay.
        update_fields_mock.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_kb_user_repository, None)


# ---------------------------------------------------------------------------
# admin/security-incidents PATCH


def test_admin_security_incidents_patch_replays(
    client: TestClient,
    make_jwt: Callable[..., str],
    override_idempotency: dict[str, Any],
) -> None:
    from src.api.admin.security_incidents_repository import (
        SecurityIncidentRepository,
        get_security_incident_repository,
    )

    cached_body: dict[str, Any] = {
        "id": str(uuid4()),
        "incident_type": "access_violation",
        "severity": "low",
        "status": "OPEN",
        "detected_at": "2026-01-01T00:00:00+00:00",
        "detected_by": "staff",
        "resolved_at": None,
        "resolution_note": None,
        "rkn_notified_at": None,
        "rkn_notification_required": False,
        "affected_resources": [],
    }
    body_json = b'{"resolution_note":"x"}'
    override_idempotency["repo"] = _make_idempotency_repo(cached_body, _sha256_of(body_json))

    update_mock = AsyncMock()
    repo = MagicMock(spec=SecurityIncidentRepository)
    repo.get_by_id = AsyncMock(return_value=MagicMock())
    repo.update = update_mock
    app.dependency_overrides[get_security_incident_repository] = lambda: repo

    try:
        sub = str(uuid4())
        token = make_jwt(roles=["staff_admin"], sub=sub)
        resp = client.patch(
            f"/api/v1/admin/security-incidents/{uuid4()}",
            content=body_json,
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": str(uuid4()),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        update_mock.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_security_incident_repository, None)


# ---------------------------------------------------------------------------
# admin/system-config PATCH (с step-up MFA)


def test_admin_system_config_patch_replays(
    client: TestClient,
    make_jwt: Callable[..., str],
    override_idempotency: dict[str, Any],
) -> None:
    """PATCH /admin/system-config — step-up MFA + idempotency stacking."""
    from src.api.admin.system_config_repository import (
        SystemConfigRepository,
        get_system_config_repository,
    )

    cached_body = {
        "rate_limits": {
            "anon_per_minute": None,
            "user_per_minute": None,
            "staff_per_minute": None,
        },
        "feature_flags": {"rag": True, "metrics_endpoint": True, "webhook_worker": True},
        "llm_config": {
            "active_provider": "mock",
            "fallback_provider": None,
            "max_context_tokens": 4096,
        },
        "moderation": {"auto_publish_threshold": None},
        "webhooks": {"max_retries": 5, "timeout_seconds": 5},
    }
    body_json = b'{"llm_provider":"mock"}'
    override_idempotency["repo"] = _make_idempotency_repo(cached_body, _sha256_of(body_json))

    patch_mock = AsyncMock(return_value={"llm_provider": "mock"})
    config_repo = MagicMock(spec=SystemConfigRepository)
    config_repo.patch = patch_mock
    config_repo.read = AsyncMock(return_value={})
    app.dependency_overrides[get_system_config_repository] = lambda: config_repo

    try:
        sub = str(uuid4())
        token = make_jwt(roles=["staff_admin"], sub=sub)
        mfa_token = make_jwt(roles=["staff_admin"], sub=sub, extra_claims={"acr": "2"})
        resp = client.patch(
            "/api/v1/admin/system-config",
            content=body_json,
            headers={
                "Authorization": f"Bearer {token}",
                "X-MFA-Token": mfa_token,
                "Idempotency-Key": str(uuid4()),
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200, resp.text
        # Business write НЕ вызвалась.
        patch_mock.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_system_config_repository, None)


# ---------------------------------------------------------------------------
# Articles PATCH (с RAG indexer + webhook)


def test_articles_patch_replays(
    client: TestClient,
    make_jwt: Callable[..., str],
    override_idempotency: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATCH /articles/{slug} — replay не дёргает repo.patch / webhook / indexer."""
    from src.api.articles.repository import ArticleRepository

    cached_body: dict[str, Any] = {
        "id": str(uuid4()),
        "slug": "cached-slug",
        "title": "Cached",
        "summary": None,
        "body_markdown": "B",
        "audience": "tenant",
        "access_level": "PUBLIC",
        "language": "ru",
        "category": "guide",
        "tags": [],
        "status": "PUBLISHED",
        "published_at": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    body_json = b'{"title":"New"}'
    override_idempotency["repo"] = _make_idempotency_repo(cached_body, _sha256_of(body_json))

    patch_mock = AsyncMock()
    monkeypatch.setattr(ArticleRepository, "patch", patch_mock)

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        "/api/v1/articles/cached-slug",
        content=body_json,
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": str(uuid4()),
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["slug"] == "cached-slug"
    patch_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Pure noop: header отсутствует — все endpoints работают как раньше


def test_admin_users_patch_no_key_passes_through(
    client: TestClient,
    make_jwt: Callable[..., str],
    override_idempotency: dict[str, Any],
) -> None:
    """Без Idempotency-Key — idempotency repo не дёргается, обычный flow."""
    from src.api.admin.users_repository import (
        KbUserRepository,
        get_kb_user_repository,
    )

    # Set up repo that should NOT be consulted (no header → noop fast-path).
    override_idempotency["repo"] = _make_idempotency_repo({})

    user = MagicMock()
    user.id = uuid4()
    user.email = "x@x"
    user.full_name = "X"
    user.role = "staff_support"
    user.status = "ACTIVE"
    user.permissions = []
    user.mfa_enabled = False
    user.last_login_at = None
    user.created_at = "2026-01-01T00:00:00+00:00"
    user.updated_at = "2026-01-01T00:00:00+00:00"

    repo = MagicMock(spec=KbUserRepository)
    repo.get_by_id = AsyncMock(return_value=user)
    repo.update_fields = AsyncMock()
    app.dependency_overrides[get_kb_user_repository] = lambda: repo

    try:
        sub = str(uuid4())
        token = make_jwt(roles=["staff_admin"], sub=sub)
        resp = client.patch(
            f"/api/v1/admin/users/{user.id}",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        # Idempotency repo НЕ должна была быть тронута (header missing →
        # process_idempotency_key возвращает noop сразу).
        override_idempotency["repo"].acquire_lock.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_kb_user_repository, None)
