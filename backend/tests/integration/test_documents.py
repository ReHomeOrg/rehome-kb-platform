"""Integration: end-to-end GET /api/v1/documents{,/{id}} с реальным Postgres.

Проверяет ADR-0003 на уровне БД:
- guest НЕ видит RESTRICTED documents (storage-level confidentiality filter),
- guest НЕ видит INTERNAL documents,
- m2m token (STAFF scope) видит все 3 уровня.

Также:
- detail возвращает signed_by / audit_log,
- 404 mask на out-of-scope id,
- download endpoint → 501.
"""

import json
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest

RAW_DSN = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://kb:kb@localhost:5432/rehome_kb"
).replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def db() -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(RAW_DSN)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def seed_documents(db: asyncpg.Connection) -> AsyncIterator[dict[str, str]]:
    """Создаёт 3 documents разной confidentiality."""
    suffix = uuid4().hex[:8]
    pub_id = uuid4()
    internal_id = uuid4()
    restricted_id = uuid4()

    signed_by_payload = json.dumps(
        [
            {
                "role": "tenant",
                "name": "Иван Иванов",
                "date": "2026-05-01T10:00:00Z",
                "method": "sms_otp",
            }
        ]
    )
    audit_log_payload = json.dumps(
        [{"actor": "sub-1", "action": "created", "ts": "2026-05-01T10:00:00Z"}]
    )

    rows = [
        (pub_id, f"Public Doc {suffix}", "A", "ACTIVE", "PUBLIC"),
        (internal_id, f"Internal Doc {suffix}", "B", "ACTIVE", "INTERNAL"),
        (restricted_id, f"Restricted Doc {suffix}", "C", "ACTIVE", "RESTRICTED"),
    ]
    for doc_id, title, category, status, conf in rows:
        await db.execute(
            """
            INSERT INTO documents
                (id, title, category, status, confidentiality, signed_by, audit_log)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb)
            """,
            doc_id,
            title,
            category,
            status,
            conf,
            signed_by_payload,
            audit_log_payload,
        )

    yield {
        "public": str(pub_id),
        "internal": str(internal_id),
        "restricted": str(restricted_id),
    }

    for doc_id, *_ in rows:
        await db.execute("DELETE FROM documents WHERE id = $1", doc_id)


def _ids_in_list(body: dict[str, object]) -> set[str]:
    data = body["data"]
    assert isinstance(data, list)
    return {item["id"] for item in data if isinstance(item, dict)}


# ---------------------------------------------------------------------------
# GET /documents — list


@pytest.mark.integration
def test_guest_list_returns_only_public(
    kb_client: httpx.Client, seed_documents: dict[str, str]
) -> None:
    response = kb_client.get("/api/v1/documents", params={"limit": 100})
    assert response.status_code == 200, response.text
    ids = _ids_in_list(response.json())
    assert seed_documents["public"] in ids
    assert seed_documents["internal"] not in ids, "guest leaked INTERNAL"
    assert seed_documents["restricted"] not in ids, "guest leaked RESTRICTED"


@pytest.mark.integration
def test_m2m_list_sees_all_three(
    kb_client: httpx.Client, seed_documents: dict[str, str], m2m_token: str
) -> None:
    response = kb_client.get(
        "/api/v1/documents",
        params={"limit": 100},
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200
    ids = _ids_in_list(response.json())
    assert seed_documents["public"] in ids
    assert seed_documents["internal"] in ids
    assert seed_documents["restricted"] in ids


@pytest.mark.integration
def test_list_category_filter(
    kb_client: httpx.Client, seed_documents: dict[str, str], m2m_token: str
) -> None:
    response = kb_client.get(
        "/api/v1/documents",
        params={"category": "B", "limit": 100},
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200
    ids = _ids_in_list(response.json())
    assert seed_documents["internal"] in ids
    assert seed_documents["public"] not in ids
    assert seed_documents["restricted"] not in ids


# ---------------------------------------------------------------------------
# GET /documents/{id} — detail


@pytest.mark.integration
def test_guest_detail_public_returns_200_with_signed_by_and_audit_log(
    kb_client: httpx.Client, seed_documents: dict[str, str]
) -> None:
    response = kb_client.get(f"/api/v1/documents/{seed_documents['public']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == seed_documents["public"]
    # PII только в detail
    assert len(body["signed_by"]) == 1
    assert len(body["audit_log"]) == 1
    assert body["signed_by"][0]["name"] == "Иван Иванов"


@pytest.mark.integration
def test_guest_detail_internal_returns_404_mask(
    kb_client: httpx.Client, seed_documents: dict[str, str]
) -> None:
    """ADR-0003 404-mask: guest не должен получить 403 (utilizes маскировку)."""
    response = kb_client.get(f"/api/v1/documents/{seed_documents['internal']}")
    assert response.status_code == 404


@pytest.mark.integration
def test_guest_detail_restricted_returns_404_mask(
    kb_client: httpx.Client, seed_documents: dict[str, str]
) -> None:
    response = kb_client.get(f"/api/v1/documents/{seed_documents['restricted']}")
    assert response.status_code == 404


@pytest.mark.integration
def test_m2m_detail_restricted_returns_200(
    kb_client: httpx.Client, seed_documents: dict[str, str], m2m_token: str
) -> None:
    response = kb_client.get(
        f"/api/v1/documents/{seed_documents['restricted']}",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200
    assert response.json()["confidentiality"] == "RESTRICTED"


# ---------------------------------------------------------------------------
# GET /documents/{id}/files/{format} — 501


@pytest.mark.integration
def test_download_returns_501(kb_client: httpx.Client, seed_documents: dict[str, str]) -> None:
    """Download endpoint — architect approved deferred to kb-files epic."""
    response = kb_client.get(f"/api/v1/documents/{seed_documents['public']}/files/pdf")
    assert response.status_code == 501
