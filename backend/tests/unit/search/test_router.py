"""Unit tests for `POST /api/v1/search` router (#134)."""

from collections.abc import Callable, Iterator
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.search.repository import RetrievalHit
from src.api.search.retrieval import RetrievalService, get_retrieval_service


def _hit(
    article_id: UUID | None = None,
    chunk_index: int = 0,
    score: float = 0.02,
    title: str = "Test article",
    slug: str = "test-article",
    text: str = "chunk text",
) -> RetrievalHit:
    return RetrievalHit(
        article_id=article_id or uuid4(),
        slug=slug,
        title=title,
        chunk_index=chunk_index,
        text=text,
        char_start=0,
        char_end=len(text),
        score=score,
    )


@pytest.fixture
def retrieval_search_mock() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture
def override_retrieval(
    retrieval_search_mock: AsyncMock,
) -> Iterator[AsyncMock]:
    svc = RetrievalService.__new__(RetrievalService)
    svc.search = retrieval_search_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_retrieval_service] = lambda: svc
    yield retrieval_search_mock
    app.dependency_overrides.pop(get_retrieval_service, None)


# ---------------------------------------------------------------------------
# auth


def test_search_requires_auth(client: TestClient, override_retrieval: AsyncMock) -> None:
    """Без JWT → 401 (require_authenticated)."""
    resp = client.post("/api/v1/search", json={"query": "hello"})
    assert resp.status_code == 401
    override_retrieval.assert_not_awaited()


def test_search_invalid_jwt_returns_401(
    client: TestClient,
    override_retrieval: AsyncMock,
) -> None:
    resp = client.post(
        "/api/v1/search",
        json={"query": "hello"},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# input validation


def test_search_empty_query_returns_422(
    client: TestClient,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_search_whitespace_query_returns_422(
    client: TestClient,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "   \n\t"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    override_retrieval.assert_not_awaited()


def test_search_oversize_query_returns_422(
    client: TestClient,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "x" * 501},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_search_limit_out_of_range_returns_422(
    client: TestClient,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    for bad_limit in (0, 51, -1):
        resp = client.post(
            "/api/v1/search",
            json={"query": "x", "limit": bad_limit},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422, f"limit={bad_limit}"


def test_search_extra_field_returns_422(
    client: TestClient,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """SearchInput extra='forbid'."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "x", "evil_field": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# happy path / response shape


def test_search_returns_200_with_empty_data(
    client: TestClient,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"data": []}


def test_search_maps_hit_to_search_hit_envelope(
    client: TestClient,
    retrieval_search_mock: AsyncMock,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    aid = uuid4()
    retrieval_search_mock.return_value = [
        _hit(
            article_id=aid,
            title="Сервисный платёж",
            slug="service-fee",
            text="невозвратный платёж...",
            score=0.025,
        ),
    ]
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "сервисный платёж"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    hit = body["data"][0]
    assert hit["type"] == "article"
    assert hit["id"] == str(aid)
    assert hit["title"] == "Сервисный платёж"
    assert hit["snippet"] == "невозвратный платёж..."
    assert hit["url"] == "/articles/service-fee"
    assert 0 <= hit["score"] <= 1
    assert hit["score"] == pytest.approx(0.025)


def test_search_clips_score_to_unit_interval(
    client: TestClient,
    retrieval_search_mock: AsyncMock,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """OpenAPI требует score в [0, 1]; clip защищает от degenerate RRF."""
    retrieval_search_mock.return_value = [_hit(score=1.7), _hit(score=-0.3)]
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    scores = [h["score"] for h in resp.json()["data"]]
    assert scores == [1.0, 0.0]


# ---------------------------------------------------------------------------
# dedupe by article


def test_search_dedupes_chunks_to_one_per_article(
    client: TestClient,
    retrieval_search_mock: AsyncMock,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """3 chunks одной article'и → 1 SearchHit (best-score wins)."""
    aid = uuid4()
    # Hits отсортированы score desc (как RRF их выдаёт). Первый chunk
    # того же article — best; остальные dedupe выкинет.
    retrieval_search_mock.return_value = [
        _hit(article_id=aid, chunk_index=0, score=0.03, text="best chunk"),
        _hit(article_id=aid, chunk_index=1, score=0.02, text="other chunk"),
        _hit(article_id=aid, chunk_index=2, score=0.01, text="worst chunk"),
    ]
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["snippet"] == "best chunk"


def test_search_dedupe_preserves_multiple_articles(
    client: TestClient,
    retrieval_search_mock: AsyncMock,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Mix chunks from 2 articles — keep 1 best per article."""
    a, b = uuid4(), uuid4()
    retrieval_search_mock.return_value = [
        _hit(article_id=a, chunk_index=0, score=0.03, slug="a", text="a-best"),
        _hit(article_id=b, chunk_index=0, score=0.025, slug="b", text="b-best"),
        _hit(article_id=a, chunk_index=1, score=0.02, slug="a", text="a-other"),
    ]
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["data"][0]["url"] == "/articles/a"
    assert body["data"][0]["snippet"] == "a-best"
    assert body["data"][1]["url"] == "/articles/b"


def test_search_overfetches_for_dedupe(
    client: TestClient,
    retrieval_search_mock: AsyncMock,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Router запрашивает limit*3 чтобы dedupe оставил ≥ limit articles."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "x", "limit": 5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    # top_k передан = limit * 3 = 15
    retrieval_search_mock.assert_awaited_once()
    assert retrieval_search_mock.call_args.kwargs["top_k"] == 15


# ---------------------------------------------------------------------------
# types filter (forward-compat)


def test_search_types_excluding_article_returns_empty(
    client: TestClient,
    retrieval_search_mock: AsyncMock,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Stage 1: types=['document'] → empty (article-only retrieval)."""
    retrieval_search_mock.return_value = [_hit()]
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "x", "types": ["document"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"data": []}
    # Retrieval НЕ вызван — early return.
    retrieval_search_mock.assert_not_awaited()


def test_search_types_with_article_proceeds_normally(
    client: TestClient,
    retrieval_search_mock: AsyncMock,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    retrieval_search_mock.return_value = [_hit()]
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "x", "types": ["article", "document"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


def test_search_unknown_type_returns_422(
    client: TestClient,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Literal enum в SearchInput — unknown value → 422."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "x", "types": ["unknown_type"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# access_levels propagation (ADR-0003 read-mask)


def test_search_propagates_access_levels_to_retrieval(
    client: TestClient,
    retrieval_search_mock: AsyncMock,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Tenant role → access_levels ⊇ {PUBLIC, LOGGED}."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "x"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    kwargs = retrieval_search_mock.call_args.kwargs
    levels = kwargs["access_levels"]
    # ADR-0003: tenant role даёт PUBLIC + LOGGED (минимум).
    from src.api.auth.scope import AccessLevel

    assert AccessLevel.PUBLIC in levels
    assert AccessLevel.LOGGED in levels


def test_search_passes_query_verbatim(
    client: TestClient,
    retrieval_search_mock: AsyncMock,
    override_retrieval: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Router не модифицирует query (только trim whitespace для validation)."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/search",
        json={"query": "  как починить кран?  "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    # Query пройден as-is (RetrievalService strip'ает сам если надо).
    assert retrieval_search_mock.call_args.kwargs["query"] == "  как починить кран?  "
