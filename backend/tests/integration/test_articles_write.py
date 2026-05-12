"""Integration: end-to-end POST /api/v1/articles c реальным Keycloak + Postgres.

Сценарии:
- staff_admin создаёт PUBLIC статью → 201 + Location + GET слью возвращает её.
- Без токена → 401.
- **staff_admin пытается HR_RESTRICTED → 403** (ADR-0003 write-extension).
- Дубликат slug → 409.

NB: m2m client в realm-export выдаёт staff_admin. Positive-тест для
staff_hr → HR_RESTRICTED покрыт unit-тестом (через `make_jwt(roles=
[\"staff_hr\"])`); integration-расширение — отдельный backlog (#29),
требует второго m2m client с staff_hr role в realm.
"""

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
async def db_cleanup() -> AsyncIterator[list[str]]:
    """Список slug'ов для cleanup в конце теста."""
    created: list[str] = []
    yield created
    conn = await asyncpg.connect(RAW_DSN)
    try:
        for slug in created:
            await conn.execute("DELETE FROM articles WHERE slug = $1", slug)
    finally:
        await conn.close()


def _payload(
    slug: str, access_level: str = "PUBLIC", status_value: str = "PUBLISHED"
) -> dict[str, str]:
    """Payload по умолчанию `status=PUBLISHED` — иначе GET после POST вернёт 404
    (ADR-0003: read фильтрует `status='PUBLISHED'`).
    """
    return {
        "slug": slug,
        "title": f"Test {slug}",
        "body_markdown": "# Content",
        "category": "guide",
        "audience": "tenant",
        "access_level": access_level,
        "status": status_value,
    }


@pytest.mark.integration
def test_create_with_real_m2m_token_returns_201_and_get_works(
    kb_client: httpx.Client,
    m2m_token: str,
    db_cleanup: list[str],
) -> None:
    slug = f"e41-create-{uuid4().hex[:8]}"
    db_cleanup.append(slug)

    create = kb_client.post(
        "/api/v1/articles",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug, "PUBLIC"),
    )
    assert create.status_code == 201, create.text
    assert create.headers["Location"] == f"/api/v1/articles/{slug}"
    body = create.json()
    assert body["slug"] == slug
    assert body["access_level"] == "PUBLIC"
    assert "id" in body
    assert len(body["id"]) > 0

    # Read-back: статья доступна и через GET.
    read = kb_client.get(f"/api/v1/articles/{slug}")
    assert read.status_code == 200
    assert read.json()["slug"] == slug


@pytest.mark.integration
def test_create_without_token_returns_401(kb_client: httpx.Client) -> None:
    response = kb_client.post(
        "/api/v1/articles",
        json=_payload(f"e41-noauth-{uuid4().hex[:8]}"),
    )
    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.security
def test_create_hr_restricted_blocked_for_staff_admin(
    kb_client: httpx.Client,
    m2m_token: str,
    db_cleanup: list[str],
) -> None:
    """ADR-0003 write-extension critical: m2m client (staff_admin) НЕ имеет
    HR_RESTRICTED → 403. Запись в БД не должна попасть.
    """
    slug = f"e41-hr-blocked-{uuid4().hex[:8]}"
    response = kb_client.post(
        "/api/v1/articles",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug, "HR_RESTRICTED"),
    )
    assert response.status_code == 403
    # Defence-in-depth: проверяем, что запись действительно не создана.
    db_cleanup.append(slug)  # на всякий случай для cleanup'а
    read = kb_client.get(
        f"/api/v1/articles/{slug}",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert read.status_code == 404


@pytest.mark.integration
def test_create_duplicate_slug_returns_409(
    kb_client: httpx.Client,
    m2m_token: str,
    db_cleanup: list[str],
) -> None:
    slug = f"e41-dup-{uuid4().hex[:8]}"
    db_cleanup.append(slug)
    first = kb_client.post(
        "/api/v1/articles",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug),
    )
    assert first.status_code == 201

    second = kb_client.post(
        "/api/v1/articles",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug),
    )
    assert second.status_code == 409


@pytest.mark.integration
def test_create_invalid_payload_returns_422(kb_client: httpx.Client, m2m_token: str) -> None:
    """Невалидный slug pattern → 422."""
    response = kb_client.post(
        "/api/v1/articles",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json={**_payload("BAD-SLUG-UPPERCASE")},
    )
    assert response.status_code == 422
