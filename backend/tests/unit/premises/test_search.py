"""Unit tests для premises search endpoint (#154)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.premises.models import PremisesCard
from src.api.premises.repository import PremisesRepository, get_premises_repository


def _make_card(**over: Any) -> PremisesCard:
    c = PremisesCard()
    c.id = uuid4()
    c.slug = "spb-test"
    c.internal_code = None
    c.status = "PUBLISHED"
    c.premises_uuid = None
    c.address = "г. Санкт-Петербург, ул. Тест"
    c.postal_code = "190000"
    c.cadastral_number = "78:14:0000000:0001"
    c.owner = {}
    c.owner_representative = None
    c.current_tenant = None
    c.financial_data = {}
    c.tenant_info = {}
    c.internal_data = {}
    c.extra_identification = {}
    c.created_at = datetime.now(UTC)
    c.updated_at = datetime.now(UTC)
    c.archived_at = None
    for k, v in over.items():
        setattr(c, k, v)
    return c


@pytest.fixture
def search_mock() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture
def override_search(search_mock: AsyncMock) -> Iterator[AsyncMock]:
    repo = PremisesRepository.__new__(PremisesRepository)
    repo.search = search_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_premises_repository] = lambda: repo
    yield search_mock
    app.dependency_overrides.pop(get_premises_repository, None)


def test_search_empty_q_returns_422(
    client: TestClient,
    override_search: AsyncMock,
) -> None:
    resp = client.post("/api/v1/premises-cards/search", json={"q": ""})
    assert resp.status_code == 422


def test_search_whitespace_q_returns_422(
    client: TestClient,
    override_search: AsyncMock,
) -> None:
    resp = client.post("/api/v1/premises-cards/search", json={"q": "   \t  "})
    assert resp.status_code == 422


def test_search_oversize_q_returns_422(
    client: TestClient,
    override_search: AsyncMock,
) -> None:
    resp = client.post("/api/v1/premises-cards/search", json={"q": "x" * 501})
    assert resp.status_code == 422


def test_search_invalid_limit(client: TestClient, override_search: AsyncMock) -> None:
    resp = client.post(
        "/api/v1/premises-cards/search",
        json={"q": "spb", "limit": 0},
    )
    assert resp.status_code == 422
    resp = client.post(
        "/api/v1/premises-cards/search",
        json={"q": "spb", "limit": 101},
    )
    assert resp.status_code == 422


def test_search_extra_field_returns_422(
    client: TestClient,
    override_search: AsyncMock,
) -> None:
    resp = client.post(
        "/api/v1/premises-cards/search",
        json={"q": "spb", "evil_field": 1},
    )
    assert resp.status_code == 422


def test_search_returns_hits_with_clipped_score(
    client: TestClient,
    override_search: AsyncMock,
) -> None:
    """ts_rank score > 1 → clipped к 1.0 (OpenAPI [0, 1] contract)."""
    card = _make_card()
    override_search.return_value = [(card, 1.7)]  # ts_rank > 1
    resp = client.post(
        "/api/v1/premises-cards/search",
        json={"q": "санкт-петербург"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    hit = body["data"][0]
    assert hit["address"] == card.address
    assert hit["slug"] == card.slug
    assert hit["score"] == 1.0  # clipped
    # PII блоки НЕ должны быть в search response (security-by-design).
    assert "owner" not in hit
    assert "financial_data" not in hit
    assert "internal_data" not in hit


def test_search_empty_results(client: TestClient, override_search: AsyncMock) -> None:
    resp = client.post(
        "/api/v1/premises-cards/search",
        json={"q": "abracadabra-never-matched"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"data": []}


@pytest.mark.asyncio
async def test_search_uses_russian_websearch_to_tsquery() -> None:
    """Repository.search строит SQL с websearch_to_tsquery('russian', ...)."""
    from unittest.mock import MagicMock

    from src.api.auth.scope import AccessLevel

    session = MagicMock()
    session.execute = AsyncMock(return_value=iter([]))
    repo = PremisesRepository(session)
    await repo.search(
        "санкт-петербург",
        frozenset({AccessLevel.PUBLIC}),
        limit=10,
    )
    session.execute.assert_awaited_once()
    stmt = session.execute.call_args.args[0]
    compiled = stmt.compile(compile_kwargs={"literal_binds": False})
    flat: list[object] = []
    for v in compiled.params.values():
        if isinstance(v, list):
            flat.extend(v)
        else:
            flat.append(v)
    # russian config + query string в bind params.
    assert "russian" in flat
    assert "санкт-петербург" in flat
    # Status filter ADR-0003 — anon видит только PUBLISHED+RENTED.
    assert "PUBLISHED" in flat
    assert "RENTED" in flat
    assert "DRAFT" not in flat
