"""Unit tests для GET /api/v1/admin/stats (#227, OpenAPI 04 §getAdminStats)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.admin.stats_repository import (
    AdminStatsRepository,
    get_admin_stats_repository,
)
from src.api.main import app


@pytest.fixture
def stats_repo_mock() -> Iterator[AsyncMock]:
    """Mock AdminStatsRepository — все методы AsyncMock."""
    repo = AdminStatsRepository.__new__(AdminStatsRepository)
    repo.count_articles_total_and_drafts = AsyncMock(return_value=(0, 0))  # type: ignore[method-assign]
    repo.count_documents_total = AsyncMock(return_value=0)  # type: ignore[method-assign]
    repo.count_chat_sessions = AsyncMock(return_value=0)  # type: ignore[method-assign]
    repo.count_chat_messages = AsyncMock(return_value=0)  # type: ignore[method-assign]
    repo.count_chat_escalations = AsyncMock(return_value=0)  # type: ignore[method-assign]
    repo.chat_rating_up_and_total = AsyncMock(return_value=(0, 0))  # type: ignore[method-assign]
    app.dependency_overrides[get_admin_stats_repository] = lambda: repo
    yield repo  # type: ignore[misc]
    app.dependency_overrides.pop(get_admin_stats_repository, None)


# ---------------------------------------------------------------------------
# Auth gating


def test_anon_returns_401(client: TestClient, stats_repo_mock: AsyncMock) -> None:
    """Без JWT → 401 (require_authenticated)."""
    resp = client.get("/api/v1/admin/stats")
    assert resp.status_code == 401


def test_tenant_returns_403(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_staff_support_alone_returns_403(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """staff_support имеет только STAFF (не LEGAL) — недостаточно для admin/stats."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_staff_admin_returns_200(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """staff_admin (STAFF + LEGAL) → 200."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_staff_legal_returns_200(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """staff_legal (STAFF + LEGAL) — тоже видит admin/stats."""
    token = make_jwt(roles=["staff_legal"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Response shape


def test_default_window_30_days(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """No `from` / `to` query → period.to ≈ now, period.from ≈ now-30d."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    period_from = datetime.fromisoformat(body["period"]["from"])
    period_to = datetime.fromisoformat(body["period"]["to"])
    now = datetime.now(UTC)
    assert (now - period_to) < timedelta(seconds=10)
    assert abs((period_to - period_from).total_seconds() - 30 * 86400) < 10


def test_response_envelope_has_4_blocks(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert set(body.keys()) == {"period", "requests", "chat", "content", "security"}


def test_real_data_from_repo_flows_through(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Counts из repo попадают в response unchanged."""
    stats_repo_mock.count_articles_total_and_drafts.return_value = (42, 7)
    stats_repo_mock.count_documents_total.return_value = 13
    stats_repo_mock.count_chat_sessions.return_value = 100
    stats_repo_mock.count_chat_messages.return_value = 350
    stats_repo_mock.count_chat_escalations.return_value = 5
    stats_repo_mock.chat_rating_up_and_total.return_value = (20, 25)

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert body["content"]["total_articles"] == 42
    assert body["content"]["pending_reviews"] == 7
    assert body["content"]["total_documents"] == 13
    assert body["chat"]["sessions"] == 100
    assert body["chat"]["messages"] == 350
    assert body["chat"]["escalations"] == 5
    assert body["chat"]["avg_rating"] == pytest.approx(0.8)  # 20/25
    # containment_rate = 1 - escalations/sessions = 1 - 5/100 = 0.95
    assert body["chat"]["containment_rate"] == pytest.approx(0.95)


def test_zero_chat_sessions_yields_zero_containment(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """0 sessions → containment_rate = 0.0 (не div-by-zero)."""
    stats_repo_mock.count_chat_sessions.return_value = 0
    stats_repo_mock.count_chat_escalations.return_value = 0
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["chat"]["containment_rate"] == 0.0


def test_no_feedback_yields_null_avg_rating(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """0 feedback → avg_rating = null (Pydantic default, frontend handles)."""
    stats_repo_mock.chat_rating_up_and_total.return_value = (0, 0)
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["chat"]["avg_rating"] is None


def test_stubbed_blocks_present_with_zeros(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """`requests` и `security` — stub'ы (no DB source); должны быть в response."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert body["requests"]["total"] == 0
    assert body["requests"]["by_endpoint"] == {}
    assert body["security"]["open_incidents"] == 0
    assert body["security"]["critical_incidents"] == 0
    assert body["security"]["overdue_pd_requests"] == 0
    assert body["chat"]["no_answer_count"] == 0


# ---------------------------------------------------------------------------
# Window validation


def test_window_from_after_to_returns_422(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """from > to → 422."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats?from=2026-12-01T00:00:00Z&to=2026-01-01T00:00:00Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_window_over_365_days_returns_422(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Window > 365 days → 422 (anti-DoS)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats?from=2024-01-01T00:00:00Z&to=2026-01-01T00:00:00Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_custom_window_passes_through_to_repo(
    client: TestClient,
    stats_repo_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """from/to → repo получает те же datetime'ы (внутренний consistency)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/stats?from=2026-04-01T00:00:00Z&to=2026-05-01T00:00:00Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    kwargs = stats_repo_mock.count_chat_sessions.call_args.kwargs
    assert kwargs["from_"].isoformat().startswith("2026-04-01")
    assert kwargs["to"].isoformat().startswith("2026-05-01")
