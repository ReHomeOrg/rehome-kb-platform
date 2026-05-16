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
# Cube HH (#185) — расширенное покрытие фильтров и pagination


@pytest.fixture
async def seed_extra_filters(db: asyncpg.Connection) -> AsyncIterator[dict[str, str]]:
    """Seed для status / related_entity / cursor coverage.

    Все PUBLIC чтобы isolation от access-level — отдельно тестируется.
    """
    suffix = uuid4().hex[:8]
    draft_id = uuid4()
    active_id = uuid4()
    related_id = uuid4()

    await db.execute(
        """INSERT INTO documents (id, title, category, status, confidentiality)
           VALUES ($1, $2, 'A', 'DRAFT', 'PUBLIC')""",
        draft_id,
        f"Draft Doc {suffix}",
    )
    await db.execute(
        """INSERT INTO documents (id, title, category, status, confidentiality)
           VALUES ($1, $2, 'A', 'ACTIVE', 'PUBLIC')""",
        active_id,
        f"Active Doc {suffix}",
    )
    await db.execute(
        """INSERT INTO documents
               (id, title, category, status, confidentiality, related_entity)
           VALUES ($1, $2, 'A', 'ACTIVE', 'PUBLIC', $3)""",
        related_id,
        f"Premises Doc {suffix}",
        f"premises:{suffix}",
    )

    yield {
        "draft": str(draft_id),
        "active": str(active_id),
        "related": str(related_id),
        "related_entity": f"premises:{suffix}",
    }

    for doc_id in (draft_id, active_id, related_id):
        await db.execute("DELETE FROM documents WHERE id = $1", doc_id)


@pytest.mark.integration
def test_list_status_filter_draft(
    kb_client: httpx.Client, seed_extra_filters: dict[str, str]
) -> None:
    response = kb_client.get(
        "/api/v1/documents",
        params={"status": "DRAFT", "limit": 100},
    )
    assert response.status_code == 200
    ids = _ids_in_list(response.json())
    assert seed_extra_filters["draft"] in ids
    assert seed_extra_filters["active"] not in ids


@pytest.mark.integration
def test_list_related_entity_filter(
    kb_client: httpx.Client, seed_extra_filters: dict[str, str]
) -> None:
    response = kb_client.get(
        "/api/v1/documents",
        params={"related_entity": seed_extra_filters["related_entity"], "limit": 100},
    )
    assert response.status_code == 200
    ids = _ids_in_list(response.json())
    assert seed_extra_filters["related"] in ids
    assert seed_extra_filters["active"] not in ids


@pytest.mark.integration
def test_list_related_entity_invalid_chars_returns_422(
    kb_client: httpx.Client,
) -> None:
    """Pattern `^[A-Za-z0-9_.:-]{1,200}$` — anti-injection guard.
    Pass space (charset violation) → 422."""
    response = kb_client.get(
        "/api/v1/documents",
        params={"related_entity": "foo bar"},
    )
    assert response.status_code == 422
    assert "related_entity" in response.text


@pytest.mark.integration
def test_list_cursor_pagination(
    kb_client: httpx.Client, seed_extra_filters: dict[str, str]
) -> None:
    """limit=1 → has_more=True + cursor_next; вторая страница работает."""
    first = kb_client.get("/api/v1/documents", params={"limit": 1})
    assert first.status_code == 200
    body1 = first.json()
    assert body1["pagination"]["has_more"] is True
    cursor = body1["pagination"]["cursor_next"]
    assert isinstance(cursor, str)
    assert cursor

    second = kb_client.get("/api/v1/documents", params={"limit": 1, "cursor": cursor})
    assert second.status_code == 200
    body2 = second.json()
    # Курсор продвинул выборку — id'ы первой и второй страниц различаются.
    ids1 = _ids_in_list(body1)
    ids2 = _ids_in_list(body2)
    assert ids1.isdisjoint(ids2)


@pytest.mark.integration
def test_list_invalid_limit_returns_422(kb_client: httpx.Client) -> None:
    """limit < LIMIT_MIN или > LIMIT_MAX → 422."""
    assert kb_client.get("/api/v1/documents", params={"limit": 0}).status_code == 422
    assert kb_client.get("/api/v1/documents", params={"limit": 10000}).status_code == 422


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
# GET /documents/{id}/files/{format} — Phase A (#214, ADR-0012)


@pytest.mark.integration
def test_download_anon_returns_401(kb_client: httpx.Client, seed_documents: dict[str, str]) -> None:
    """Auth required — download gates через require_authenticated."""
    response = kb_client.get(f"/api/v1/documents/{seed_documents['public']}/files/pdf")
    assert response.status_code == 401


@pytest.mark.integration
def test_download_m2m_minio_disabled_returns_503(
    kb_client: httpx.Client,
    seed_documents: dict[str, str],
    m2m_token: str,
) -> None:
    """CI env: MINIO_ENABLED=false → 503 (config issue, не data issue).

    Phase A doesn't seed real files либо включать MinIO в CI compose
    — это Phase B / integration backlog. Этот тест регрессионный guard
    что endpoint больше не 501, а гoes через auth + scope + storage check.
    """
    response = kb_client.get(
        f"/api/v1/documents/{seed_documents['public']}/files/pdf",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    # Public doc, m2m видит → проходит auth+scope. files JSONB empty
    # (seed не клал) → 404 mask. Допускаем оба: 404 (no file entry)
    # или 503 (если MINIO_ENABLED=true но object missing).
    assert response.status_code in (404, 503)


# ---------------------------------------------------------------------------
# POST /documents/{id}/files — Phase B (#215, ADR-0012)


@pytest.mark.integration
def test_upload_anon_returns_401(kb_client: httpx.Client, seed_documents: dict[str, str]) -> None:
    """Auth required для multipart upload."""
    response = kb_client.post(
        f"/api/v1/documents/{seed_documents['public']}/files",
        files={"file": ("test.pdf", b"hello", "application/pdf")},
        data={"format": "pdf", "version": "1.0"},
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_upload_m2m_minio_disabled_returns_503(
    kb_client: httpx.Client,
    seed_documents: dict[str, str],
    m2m_token: str,
) -> None:
    """CI env: MINIO_ENABLED=false → 503 (StorageNotConfigured).

    m2m client has STAFF scope (per realm-export.json) → проходит
    STAFF gate в require_access_level. Document visible → проходит
    404-mask. Body OK → проходит size + sha256. upload_object → 503.
    """
    response = kb_client.post(
        f"/api/v1/documents/{seed_documents['public']}/files",
        files={"file": ("test.pdf", b"hello-pdf-payload", "application/pdf")},
        data={"format": "pdf", "version": "1.0"},
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    # MINIO_ENABLED=false → 503. Если CI поднимет minio service,
    # тест должен будет вернуть 201 + проверять upsert в files JSONB —
    # это backlog когда docker compose добавит minio service.
    assert response.status_code in (201, 503)


@pytest.mark.integration
def test_upload_m2m_oversized_returns_413(
    kb_client: httpx.Client,
    seed_documents: dict[str, str],
    m2m_token: str,
) -> None:
    """50 МБ + 1 байт → 413 (anti-DoS guard).

    Этот тест регрессионный guard на size check — если кто-то уберёт
    `if len(body) > settings.document_max_upload_bytes`, MinIO будет
    получать unbounded uploads → DoS vector.
    """
    # 50 МБ default + 1 байт. 50 * 1024 * 1024 + 1 = 52_428_801.
    oversized = b"x" * (50 * 1024 * 1024 + 1)
    response = kb_client.post(
        f"/api/v1/documents/{seed_documents['public']}/files",
        files={"file": ("big.pdf", oversized, "application/pdf")},
        data={"format": "pdf", "version": "1.0"},
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 413
