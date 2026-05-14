"""Integration: `POST /api/v1/search` smoke + auth contract (#134).

Deep retrieval behavior (RRF fusion, vector cosine distance, access_level
filter) — unit-tested. Здесь только end-to-end contract:
- 401 без auth.
- 200 с m2m токеном.
- 422 на invalid input.
- Response shape matches OpenAPI `SearchHit`.

Embeddings seeding в integration требует чтобы worker (или сам тест) их
загрузил. Здесь мы не seed'им — проверяем path жив, ответ структурно
валиден. Result data может быть пустым (нет embeddings под mock-v1
model'ом в kb) и это OK для contract'а.
"""

import httpx
import pytest


@pytest.mark.integration
def test_search_requires_auth(kb_client: httpx.Client) -> None:
    """Без Authorization header — 401."""
    response = kb_client.post("/api/v1/search", json={"query": "hello"})
    assert response.status_code == 401


@pytest.mark.integration
def test_search_with_m2m_token_returns_200(
    kb_client: httpx.Client,
    m2m_token: str,
) -> None:
    response = kb_client.post(
        "/api/v1/search",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json={"query": "договор аренды"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "data" in body
    assert isinstance(body["data"], list)
    # Каждый hit — `SearchHit` per OpenAPI.
    for hit in body["data"]:
        assert hit["type"] == "article"
        assert isinstance(hit["id"], str)
        assert isinstance(hit["title"], str)
        assert 0.0 <= hit["score"] <= 1.0
        assert hit["url"].startswith("/articles/")


@pytest.mark.integration
def test_search_empty_query_returns_422(
    kb_client: httpx.Client,
    m2m_token: str,
) -> None:
    response = kb_client.post(
        "/api/v1/search",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json={"query": ""},
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_search_whitespace_query_returns_422(
    kb_client: httpx.Client,
    m2m_token: str,
) -> None:
    response = kb_client.post(
        "/api/v1/search",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json={"query": "   \t  "},
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_search_invalid_limit_returns_422(
    kb_client: httpx.Client,
    m2m_token: str,
) -> None:
    response = kb_client.post(
        "/api/v1/search",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json={"query": "x", "limit": 0},
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_search_invalid_type_returns_422(
    kb_client: httpx.Client,
    m2m_token: str,
) -> None:
    response = kb_client.post(
        "/api/v1/search",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json={"query": "x", "types": ["unknown"]},
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_search_types_excluding_article_returns_empty(
    kb_client: httpx.Client,
    m2m_token: str,
) -> None:
    """Stage 1: types=['document'] — silent empty (forward-compat)."""
    response = kb_client.post(
        "/api/v1/search",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json={"query": "договор", "types": ["document"]},
    )
    assert response.status_code == 200
    assert response.json() == {"data": []}


@pytest.mark.integration
def test_search_invalid_jwt_returns_401(kb_client: httpx.Client) -> None:
    response = kb_client.post(
        "/api/v1/search",
        headers={"Authorization": "Bearer not-a-jwt"},
        json={"query": "x"},
    )
    assert response.status_code == 401
