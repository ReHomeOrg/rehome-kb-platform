"""E4.x #104: verify webhook router writes audit_log rows."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.main import app
from src.api.webhooks.delivery_repository import (
    WebhookDeliveryRepository,
    get_delivery_repository,
)
from src.api.webhooks.models import Webhook
from src.api.webhooks.repository import WebhookRepository, get_webhook_repository


def _make_webhook(client_id: str = "alice-sub") -> Webhook:
    w = Webhook()
    w.id = uuid4()
    w.client_id = client_id
    w.url = "https://example.com/hook"
    w.events = ["article.published"]
    w.secret = "secret-32-chars-len-padding-here"
    w.description = None
    w.created_at = datetime.now(UTC)
    w.last_delivery_at = None
    w.last_delivery_status = None
    w.deleted_at = None
    return w


@pytest.fixture
def audit_mock() -> Iterator[AsyncMock]:
    record = AsyncMock()
    fake = MagicMock(spec=AuditRepository)
    fake.record = record
    app.dependency_overrides[get_audit_repository] = lambda: fake
    yield record
    app.dependency_overrides.pop(get_audit_repository, None)


@pytest.fixture
def override_create() -> Iterator[AsyncMock]:
    create = AsyncMock(return_value=_make_webhook())
    repo = WebhookRepository.__new__(WebhookRepository)
    repo.create = create  # type: ignore[method-assign]
    app.dependency_overrides[get_webhook_repository] = lambda: repo
    yield create
    app.dependency_overrides.pop(get_webhook_repository, None)


# ---------------------------------------------------------------------------
# POST


def test_post_writes_webhooks_created_audit(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_mock: AsyncMock,
    override_create: AsyncMock,
) -> None:
    token = make_jwt(roles=["staff_admin"], sub="alice-sub")
    with patch("src.api.webhooks.router.validate_webhook_url", return_value=None):
        resp = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["article.published"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 201
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["actor_sub"] == "alice-sub"
    assert kwargs["action"] == "webhooks.created"
    assert kwargs["resource_type"] == "webhook"
    assert kwargs["metadata"]["url"] == "https://example.com/hook"
    assert kwargs["metadata"]["events"] == ["article.published"]


def test_post_does_not_leak_secret_in_audit(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_mock: AsyncMock,
    override_create: AsyncMock,
) -> None:
    """ФЗ-152: secret НЕ должен попадать в audit metadata."""
    token = make_jwt(roles=["staff_admin"], sub="alice-sub")
    with patch("src.api.webhooks.router.validate_webhook_url", return_value=None):
        resp = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["article.published"],
                "secret": "super-secret-token-xxx",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 201
    audit_mock.assert_awaited_once()
    metadata = audit_mock.call_args.kwargs["metadata"]
    assert "secret" not in metadata
    assert "super-secret-token-xxx" not in str(metadata)


def test_post_ssrf_400_does_not_write_audit(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_mock: AsyncMock,
    override_create: AsyncMock,
) -> None:
    token = make_jwt(roles=["staff_admin"], sub="alice-sub")
    resp = client.post(
        "/api/v1/webhooks",
        json={
            "url": "http://localhost:8080/hook",
            "events": ["article.published"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    audit_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# DELETE


def test_delete_writes_webhooks_deleted_audit(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_mock: AsyncMock,
) -> None:
    repo = WebhookRepository.__new__(WebhookRepository)
    repo.soft_delete = AsyncMock(return_value=True)  # type: ignore[method-assign]
    app.dependency_overrides[get_webhook_repository] = lambda: repo
    try:
        webhook_id = uuid4()
        token = make_jwt(roles=["staff_admin"], sub="alice-sub")
        resp = client.delete(
            f"/api/v1/webhooks/{webhook_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204
        audit_mock.assert_awaited_once()
        kwargs = audit_mock.call_args.kwargs
        assert kwargs["action"] == "webhooks.deleted"
        assert kwargs["resource_id"] == str(webhook_id)
    finally:
        app.dependency_overrides.pop(get_webhook_repository, None)


def test_delete_404_does_not_write_audit(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_mock: AsyncMock,
) -> None:
    repo = WebhookRepository.__new__(WebhookRepository)
    repo.soft_delete = AsyncMock(return_value=False)  # type: ignore[method-assign]
    app.dependency_overrides[get_webhook_repository] = lambda: repo
    try:
        token = make_jwt(roles=["staff_admin"], sub="alice-sub")
        resp = client.delete(
            f"/api/v1/webhooks/{uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
        audit_mock.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_webhook_repository, None)


# ---------------------------------------------------------------------------
# POST /test


def test_test_writes_webhooks_tested_audit(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_mock: AsyncMock,
) -> None:
    webhook = _make_webhook()
    wh_repo = WebhookRepository.__new__(WebhookRepository)
    wh_repo.get_by_id_and_owner = AsyncMock(return_value=webhook)  # type: ignore[method-assign]
    app.dependency_overrides[get_webhook_repository] = lambda: wh_repo

    enqueue_result = MagicMock(id=uuid4())
    deliv_repo = WebhookDeliveryRepository.__new__(WebhookDeliveryRepository)
    deliv_repo.enqueue = AsyncMock(return_value=enqueue_result)  # type: ignore[method-assign]
    app.dependency_overrides[get_delivery_repository] = lambda: deliv_repo

    try:
        token = make_jwt(roles=["staff_admin"], sub="alice-sub")
        resp = client.post(
            f"/api/v1/webhooks/{webhook.id}/test",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202
        audit_mock.assert_awaited_once()
        kwargs = audit_mock.call_args.kwargs
        assert kwargs["action"] == "webhooks.tested"
        assert kwargs["resource_id"] == str(webhook.id)
    finally:
        app.dependency_overrides.pop(get_webhook_repository, None)
        app.dependency_overrides.pop(get_delivery_repository, None)
