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


# ============================================================
# PUT /api/v1/articles/{slug} — replace endpoint (E4.3)
# ============================================================


@pytest.mark.integration
def test_put_roundtrip_post_then_put_then_get(
    kb_client: httpx.Client,
    m2m_token: str,
    db_cleanup: list[str],
) -> None:
    """POST → PUT → GET roundtrip. Содержимое после PUT возвращается GET'ом."""
    slug = f"e43-rt-{uuid4().hex[:8]}"
    db_cleanup.append(slug)

    # POST initial state.
    post = kb_client.post(
        "/api/v1/articles",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug, "PUBLIC"),
    )
    assert post.status_code == 201, post.text

    # PUT — меняем title и body, оставляем access_level=PUBLIC.
    new_payload = {
        **_payload(slug, "PUBLIC"),
        "title": "Updated title via PUT",
        "body_markdown": "# Updated body",
    }
    put = kb_client.put(
        f"/api/v1/articles/{slug}",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=new_payload,
    )
    assert put.status_code == 200, put.text
    assert put.json()["title"] == "Updated title via PUT"

    # GET без токена возвращает обновлённое содержимое.
    get_resp = kb_client.get(f"/api/v1/articles/{slug}")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["title"] == "Updated title via PUT"
    assert body["body_markdown"] == "# Updated body"


@pytest.mark.integration
@pytest.mark.security
def test_put_hr_restricted_target_blocked_for_staff_admin(
    kb_client: httpx.Client,
    m2m_token: str,
    db_cleanup: list[str],
) -> None:
    """ADR-0003 Level-2: m2m client (staff_admin) не может ставить target=HR_RESTRICTED."""
    slug = f"e43-hr-target-{uuid4().hex[:8]}"
    db_cleanup.append(slug)

    # Сначала POST PUBLIC статью.
    post = kb_client.post(
        "/api/v1/articles",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug, "PUBLIC"),
    )
    assert post.status_code == 201

    # PUT с target=HR_RESTRICTED → 403 (target check срабатывает ДО source check).
    put = kb_client.put(
        f"/api/v1/articles/{slug}",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug, "HR_RESTRICTED"),
    )
    assert put.status_code == 403


@pytest.mark.integration
def test_put_nonexistent_article_returns_404(kb_client: httpx.Client, m2m_token: str) -> None:
    slug = f"e43-missing-{uuid4().hex[:8]}"
    response = kb_client.put(
        f"/api/v1/articles/{slug}",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug),
    )
    assert response.status_code == 404


@pytest.mark.integration
def test_put_slug_mismatch_returns_422(kb_client: httpx.Client, m2m_token: str) -> None:
    response = kb_client.put(
        "/api/v1/articles/path-slug",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload("body-slug-different"),
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_put_without_token_returns_401(kb_client: httpx.Client) -> None:
    response = kb_client.put(
        "/api/v1/articles/whatever",
        json=_payload("whatever"),
    )
    assert response.status_code == 401


# ============================================================
# DELETE /api/v1/articles/{slug} — soft-delete (E4.4)
# ============================================================


@pytest.mark.integration
def test_delete_archives_and_get_returns_404(
    kb_client: httpx.Client,
    m2m_token: str,
    db_cleanup: list[str],
) -> None:
    """POST PUBLISHED → DELETE → GET без токена возвращает 404 (read скрывает ARCHIVED)."""
    slug = f"e44-arch-{uuid4().hex[:8]}"
    db_cleanup.append(slug)

    post = kb_client.post(
        "/api/v1/articles",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug, "PUBLIC"),
    )
    assert post.status_code == 201

    delete = kb_client.delete(
        f"/api/v1/articles/{slug}",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert delete.status_code == 204

    # GET без токена: read filter `status='PUBLISHED'` скрывает ARCHIVED.
    get_resp = kb_client.get(f"/api/v1/articles/{slug}")
    assert get_resp.status_code == 404


@pytest.mark.integration
def test_delete_idempotent_204_on_second_call(
    kb_client: httpx.Client,
    m2m_token: str,
    db_cleanup: list[str],
) -> None:
    """RFC 7231: повторная DELETE на уже-ARCHIVED статью → 204."""
    slug = f"e44-idem-{uuid4().hex[:8]}"
    db_cleanup.append(slug)

    post = kb_client.post(
        "/api/v1/articles",
        headers={"Authorization": f"Bearer {m2m_token}"},
        json=_payload(slug, "PUBLIC"),
    )
    assert post.status_code == 201

    first = kb_client.delete(
        f"/api/v1/articles/{slug}",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert first.status_code == 204

    second = kb_client.delete(
        f"/api/v1/articles/{slug}",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert second.status_code == 204


@pytest.mark.integration
def test_delete_nonexistent_returns_404(kb_client: httpx.Client, m2m_token: str) -> None:
    response = kb_client.delete(
        f"/api/v1/articles/e44-missing-{uuid4().hex[:8]}",
        headers={"Authorization": f"Bearer {m2m_token}"},
    )
    assert response.status_code == 404


@pytest.mark.integration
def test_delete_without_token_returns_401(kb_client: httpx.Client) -> None:
    response = kb_client.delete("/api/v1/articles/whatever")
    assert response.status_code == 401
