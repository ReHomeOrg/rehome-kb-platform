"""Unit-тесты POST/GET/DELETE /api/v1/webhooks (E5.1 #87)."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.webhooks.models import Webhook
from src.api.webhooks.repository import WebhookRepository, get_webhook_repository


def _make_webhook(client_id: str = "alice") -> Webhook:
    w = Webhook()
    w.id = uuid4()
    w.client_id = client_id
    w.url = "https://example.com/hook"
    w.events = ["article.published"]
    w.secret = "secret-32-chars-len-padding-here"
    w.description = "test"
    w.created_at = datetime.now(UTC)
    w.last_delivery_at = None
    w.last_delivery_status = None
    w.deleted_at = None
    return w


@pytest.fixture
def create_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def list_mock() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture
def delete_mock() -> AsyncMock:
    return AsyncMock(return_value=False)


@pytest.fixture
def override_repo(
    create_mock: AsyncMock, list_mock: AsyncMock, delete_mock: AsyncMock
) -> Iterator[tuple[AsyncMock, AsyncMock, AsyncMock]]:
    repo = WebhookRepository.__new__(WebhookRepository)
    repo.create = create_mock  # type: ignore[method-assign]
    repo.list_by_owner = list_mock  # type: ignore[method-assign]
    repo.soft_delete = delete_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_webhook_repository] = lambda: repo
    yield create_mock, list_mock, delete_mock
    app.dependency_overrides.pop(get_webhook_repository, None)


# ---------------------------------------------------------------------------
# Auth gating


def test_post_without_jwt_returns_401(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
) -> None:
    resp = client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/", "events": ["article.published"]},
    )
    assert resp.status_code == 401


def test_get_without_jwt_returns_401(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
) -> None:
    resp = client.get("/api/v1/webhooks")
    assert resp.status_code == 401


def test_delete_without_jwt_returns_401(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
) -> None:
    resp = client.delete(f"/api/v1/webhooks/{uuid4()}")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST


def test_post_with_valid_jwt_creates_webhook(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    create_mock, _, _ = override_repo
    create_mock.return_value = _make_webhook(client_id="alice-sub")

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
    body = resp.json()
    assert body["client_id"] == "alice-sub"
    # Secret returned for client to save
    assert "secret" in body


def test_post_ssrf_blocks_internal_url(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """SSRF: real localhost URL → 400 (no need to mock — resolved by OS)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/webhooks",
        json={
            "url": "http://localhost:8080/hook",
            "events": ["article.published"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "private IP" in resp.json()["detail"]


def test_post_invalid_event_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/", "events": ["bogus.event"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_post_empty_events_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/", "events": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET


def test_get_returns_owned_webhooks(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    _, list_mock, _ = override_repo
    list_mock.return_value = [_make_webhook(client_id="alice")]
    token = make_jwt(roles=["staff_admin"], sub="alice")
    resp = client.get("/api/v1/webhooks", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    # Repo called with caller's sub
    assert list_mock.call_args.args[0] == "alice"


def test_get_empty_list(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    _, list_mock, _ = override_repo
    list_mock.return_value = []
    token = make_jwt(roles=["staff_admin"], sub="alice")
    resp = client.get("/api/v1/webhooks", headers={"Authorization": f"Bearer {token}"})
    assert resp.json() == {"data": []}


# ---------------------------------------------------------------------------
# DELETE


def test_delete_existing_returns_204(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    _, _, delete_mock = override_repo
    delete_mock.return_value = True
    token = make_jwt(roles=["staff_admin"], sub="alice")
    resp = client.delete(
        f"/api/v1/webhooks/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204


def test_delete_nonexistent_returns_404_mask(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    _, _, delete_mock = override_repo
    delete_mock.return_value = False
    token = make_jwt(roles=["staff_admin"], sub="alice")
    resp = client.delete(
        f"/api/v1/webhooks/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_delete_invalid_uuid_returns_422(
    client: TestClient,
    override_repo: tuple[AsyncMock, AsyncMock, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub="alice")
    resp = client.delete(
        "/api/v1/webhooks/not-a-uuid",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
