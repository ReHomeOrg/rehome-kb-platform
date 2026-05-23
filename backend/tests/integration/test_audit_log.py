"""Integration: end-to-end /api/v1/audit-log с реальным Postgres + Keycloak.

Покрывает:
- Anon → 401 на оба endpoint'а (search + CSV export).
- m2m staff_admin (LEGAL granted) → 200.
- Фильтры передаются: actor_sub / resource_type / action.
- q-substring search метадаты (#181).
- CSV export — Content-Disposition + BOM + headers.
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
async def seed_audit_rows(db: asyncpg.Connection) -> AsyncIterator[dict[str, str]]:
    """Создаёт 3 audit rows с разными actor/action/metadata для теста фильтров."""
    suffix = uuid4().hex[:8]
    actor_a = f"user-a-{suffix}"
    actor_b = f"user-b-{suffix}"
    needle = f"needle-{suffix}"

    rows = [
        (actor_a, "articles.created", "article", "slug-1", json.dumps({"tag": needle})),
        (actor_a, "articles.updated", "article", "slug-1", json.dumps({"x": 1})),
        (actor_b, "webhook.created", "webhook", "wh-1", json.dumps({"y": 2})),
    ]
    for actor, action, rtype, rid, metadata in rows:
        await db.execute(
            """INSERT INTO audit_log (actor_sub, action, resource_type, resource_id, metadata)
               VALUES ($1, $2, $3, $4, $5::jsonb)""",
            actor,
            action,
            rtype,
            rid,
            metadata,
        )

    yield {"actor_a": actor_a, "actor_b": actor_b, "needle": needle, "suffix": suffix}

    await db.execute("DELETE FROM audit_log WHERE actor_sub IN ($1, $2)", actor_a, actor_b)


# ---------------------------------------------------------------------------
# Auth boundary


@pytest.mark.integration
def test_audit_anon_returns_401(kb_client: httpx.Client) -> None:
    response = kb_client.get("/api/v1/audit-log")
    assert response.status_code == 401


@pytest.mark.integration
def test_audit_csv_anon_returns_401(kb_client: httpx.Client) -> None:
    response = kb_client.get("/api/v1/audit-log/export.csv")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Positive path (m2m staff_admin has LEGAL)


@pytest.mark.integration
def test_audit_m2m_staff_admin_returns_200(kb_client: httpx.Client, m2m_token: str) -> None:
    response = kb_client.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "pagination" in body


@pytest.mark.integration
def test_audit_actor_filter(
    kb_client: httpx.Client,
    seed_audit_rows: dict[str, str],
    m2m_token: str,
) -> None:
    """`actor_sub` filter returns только rows того actor'а."""
    response = kb_client.get(
        "/api/v1/audit-log",
        params={"actor_sub": seed_audit_rows["actor_a"], "limit": 100},
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    for row in data:
        assert row["actor_sub"] == seed_audit_rows["actor_a"]


@pytest.mark.integration
def test_audit_action_filter(
    kb_client: httpx.Client,
    seed_audit_rows: dict[str, str],
    m2m_token: str,
) -> None:
    response = kb_client.get(
        "/api/v1/audit-log",
        params={"action": "articles.created", "limit": 100},
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200
    for row in response.json()["data"]:
        assert row["action"] == "articles.created"


@pytest.mark.integration
def test_audit_q_substring_search(
    kb_client: httpx.Client,
    seed_audit_rows: dict[str, str],
    m2m_token: str,
) -> None:
    """`q` ILIKE substring (#181) находит rows с metadata containing needle."""
    response = kb_client.get(
        "/api/v1/audit-log",
        params={"q": seed_audit_rows["needle"], "limit": 100},
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    # Один row matched needle в metadata.
    matched = [r for r in data if seed_audit_rows["needle"] in json.dumps(r["metadata"])]
    assert len(matched) >= 1


# ---------------------------------------------------------------------------
# CSV export


@pytest.mark.integration
def test_audit_csv_export_returns_csv_content_type(kb_client: httpx.Client, m2m_token: str) -> None:
    response = kb_client.get(
        "/api/v1/audit-log/export.csv",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers.get("content-disposition", "")


@pytest.mark.integration
def test_audit_csv_export_includes_utf8_bom(kb_client: httpx.Client, m2m_token: str) -> None:
    """UTF-8 BOM в начале — Excel cyrillic decode без manual override."""
    response = kb_client.get(
        "/api/v1/audit-log/export.csv",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")


@pytest.mark.integration
def test_audit_csv_export_includes_header_row(kb_client: httpx.Client, m2m_token: str) -> None:
    response = kb_client.get(
        "/api/v1/audit-log/export.csv",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 200
    # Strip BOM, decode first line.
    body = response.content.lstrip(b"\xef\xbb\xbf").decode("utf-8")
    header = body.splitlines()[0]
    assert "created_at" in header
    assert "actor_sub" in header
    assert "action" in header
    assert "metadata" in header


# JSONL export (#352) — unit tests в tests/unit/test_audit_search.py
# (run against in-process FastAPI app, не требуют deployed service).
