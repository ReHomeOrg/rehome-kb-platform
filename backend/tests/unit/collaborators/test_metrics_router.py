"""Router tests для /collaborators/{id}/metrics (Slice 4)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.collaborators.models import Collaborator
from src.api.db import get_session
from src.api.main import app


def _make_collab(group: str = "A") -> Collaborator:
    c = Collaborator()
    c.id = uuid4()
    c.financial_group = group
    c.status = "ACTIVE"
    c.rating = Decimal("4.5")
    c.portal_access_level = "FULL"
    c.onboarding_source = "staff_invite"
    c.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    c.updated_at = datetime(2026, 5, 17, tzinfo=UTC)
    return c


@pytest.fixture
def fake_session() -> Iterator[MagicMock]:
    s = MagicMock()
    s.commit = AsyncMock()
    s.execute = AsyncMock()

    async def _yield() -> Any:
        yield s

    app.dependency_overrides[get_session] = _yield
    yield s
    app.dependency_overrides.pop(get_session, None)


def _make_result(
    scalar: Any = None,
    mapping_one: dict[str, Any] | None = None,
    all_rows: list[Any] | None = None,
) -> MagicMock:
    r = MagicMock()
    if scalar is not None:
        r.scalar_one_or_none = MagicMock(return_value=scalar)
        r.scalar_one = MagicMock(return_value=scalar)
    elif scalar is None and all_rows is None:
        r.scalar_one_or_none = MagicMock(return_value=None)
        r.scalar_one = MagicMock(return_value=0)
    if mapping_one is not None:
        # .mappings().one() → dict-like
        mappings_obj = MagicMock()
        mappings_obj.one = MagicMock(return_value=mapping_one)
        r.mappings = MagicMock(return_value=mappings_obj)
    if all_rows is not None:
        r.all = MagicMock(return_value=all_rows)
    return r


# ---------------------------------------------------------------------------


def test_metrics_anon_returns_403(client: TestClient, fake_session: MagicMock) -> None:
    resp = client.get(f"/api/v1/collaborators/{uuid4()}/metrics")
    assert resp.status_code == 403


def test_metrics_404_when_collaborator_not_visible(
    client: TestClient,
    fake_session: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    fake_session.execute.side_effect = [_make_result(scalar=None)]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/collaborators/{uuid4()}/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_metrics_returns_aggregations(
    client: TestClient,
    fake_session: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """Happy path — rating agg + distribution + premises_count."""
    collab = _make_collab("A")

    # Mock execute calls в порядке:
    # 1. collab lookup → scalar_one_or_none = collab
    # 2. rating avg/count → one() returns row (avg=Decimal('4.5'), count=10)
    # 3. distribution group_by → all() returns [(5, 7), (4, 2), (3, 1)]
    # 4. premises count → scalar_one() = 3
    rating_mapping = {"avg_rating": Decimal("4.5"), "total": 10}
    fake_session.execute.side_effect = [
        _make_result(scalar=collab),
        _make_result(mapping_one=rating_mapping),
        _make_result(all_rows=[(5, 7), (4, 2), (3, 1)]),
        _make_result(scalar=3),
    ]

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/collaborators/{collab.id}/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rating"]["average"] == 4.5
    assert body["rating"]["count"] == 10
    assert body["rating"]["distribution"] == {"1": 0, "2": 0, "3": 1, "4": 2, "5": 7}
    assert body["premises_served"] == 3
    assert body["lifecycle"]["current_status"] == "ACTIVE"
    assert body["lifecycle"]["portal_access_level"] == "FULL"
    # Backlog fields — null per Slice 4 §intro.
    assert body["orders_by_status"] is None
    assert body["revenue_rub"] is None
    assert body["complaints_count"] is None


def test_metrics_period_filter_passed_to_query(
    client: TestClient,
    fake_session: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """`from` / `to` query params propagate в response.period."""
    collab = _make_collab("A")
    fake_session.execute.side_effect = [
        _make_result(scalar=collab),
        _make_result(mapping_one={"avg_rating": None, "total": 0}),
        _make_result(all_rows=[]),
        _make_result(scalar=0),
    ]

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/collaborators/{collab.id}/metrics"
        "?from=2026-04-01T00:00:00Z&to=2026-05-01T00:00:00Z",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Pydantic alias `from_` ↔ `from` в JSON.
    assert body["period"]["from"] == "2026-04-01T00:00:00Z"
    assert body["period"]["to"] == "2026-05-01T00:00:00Z"


def test_metrics_empty_reviews_returns_null_average(
    client: TestClient,
    fake_session: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    collab = _make_collab("A")
    fake_session.execute.side_effect = [
        _make_result(scalar=collab),
        _make_result(mapping_one={"avg_rating": None, "total": 0}),
        _make_result(all_rows=[]),
        _make_result(scalar=0),
    ]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/collaborators/{collab.id}/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert body["rating"]["average"] is None
    assert body["rating"]["count"] == 0
    # Distribution всегда содержит 1-5 keys (даже если все нули).
    assert body["rating"]["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
