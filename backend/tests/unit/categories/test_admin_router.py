"""Router-level tests для /admin/categories (ADR-0024, #355)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.categories.admin_repository import (
    ArchivedParentError,
    CategoryAdminRepository,
    CycleDetectedError,
    ParentNotFoundError,
    SlugConflictError,
    get_category_admin_repository,
)
from src.api.categories.models import Category
from src.api.main import app


def _make_category(slug: str = "x", archived: bool = False) -> Category:
    c = Category()
    c.id = uuid4()
    c.slug = slug
    c.title = "X"
    c.description = None
    c.parent_id = None
    c.created_at = datetime.now(UTC)
    c.updated_at = datetime.now(UTC)
    c.archived_at = datetime.now(UTC) if archived else None
    return c


@pytest.fixture
def repo_mock() -> Iterator[Any]:
    """Override CategoryAdminRepository — stubbed CRUD.

    Также overrides `get_session` (articles tests могут оставить
    pollute'нутый override на `object()` без commit method).
    """
    from src.api.db import get_session

    repo = MagicMock(spec=CategoryAdminRepository)
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.archive = AsyncMock()
    repo.get_by_id = AsyncMock()

    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    async def _session_factory() -> Any:
        yield session

    app.dependency_overrides[get_category_admin_repository] = lambda: repo
    app.dependency_overrides[get_session] = _session_factory
    yield repo
    app.dependency_overrides.pop(get_category_admin_repository, None)
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# RBAC


def test_post_anon_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/admin/categories",
        json={"slug": "x", "title": "X"},
    )
    assert resp.status_code == 401


def test_post_staff_support_returns_403(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    """staff_support имеет STAFF без LEGAL → 403."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/categories",
        json={"slug": "x", "title": "X"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST happy path + errors


def test_post_creates_category(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    cat = _make_category(slug="finance")
    repo_mock.create.return_value = cat

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/categories",
        json={"slug": "finance", "title": "Финансы"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "finance"
    assert body["archived_at"] is None


def test_post_slug_conflict_returns_409(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    repo_mock.create.side_effect = SlugConflictError("slug 'x' уже занят")
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/categories",
        json={"slug": "x", "title": "X"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


def test_post_unknown_parent_returns_422(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    repo_mock.create.side_effect = ParentNotFoundError("parent missing")
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/categories",
        json={"slug": "x", "title": "X", "parent_id": str(uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_post_archived_parent_returns_422(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    repo_mock.create.side_effect = ArchivedParentError("parent archived")
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/categories",
        json={"slug": "x", "title": "X", "parent_id": str(uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_post_slug_invalid_pattern_returns_422(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    """Slug pattern enforces lowercase ascii + digits + hyphens."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/categories",
        json={"slug": "Capital", "title": "X"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET


def test_get_returns_404_when_not_found(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    repo_mock.get_by_id.return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/categories/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_get_returns_archived_for_admin(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    """Admin видит archived row тоже (в отличие от public GET /categories)."""
    archived = _make_category(slug="dead", archived=True)
    repo_mock.get_by_id.return_value = archived
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/categories/{archived.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is not None


# ---------------------------------------------------------------------------
# PATCH


def test_patch_cycle_detection_returns_422(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    cat = _make_category()
    repo_mock.get_by_id.return_value = cat
    repo_mock.update.side_effect = CycleDetectedError("cycle in parent chain")
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/categories/{cat.id}",
        json={"parent_id": str(uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_patch_title_only(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    cat = _make_category()
    repo_mock.get_by_id.return_value = cat
    repo_mock.update.return_value = cat
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/categories/{cat.id}",
        json={"title": "Новое название"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    update_kwargs = repo_mock.update.call_args.kwargs
    # parent_id_set=False — title-only.
    assert update_kwargs["parent_id_set"] is False
    assert update_kwargs["title"] == "Новое название"


def test_patch_slug_rejected_by_extra_forbid(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    """Slug — READ-ONLY (ADR Open Q 2). Попытка передать → 422."""
    cat = _make_category()
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/categories/{cat.id}",
        json={"slug": "new-slug"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_patch_empty_body_returns_current(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    """Empty body — no-op (idempotent), no update call."""
    cat = _make_category()
    repo_mock.get_by_id.return_value = cat
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.patch(
        f"/api/v1/admin/categories/{cat.id}",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    repo_mock.update.assert_not_called()


# ---------------------------------------------------------------------------
# DELETE (archive)


def test_delete_returns_204(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    cat = _make_category()
    repo_mock.get_by_id.return_value = cat
    repo_mock.archive.return_value = cat
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/admin/categories/{cat.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204


def test_delete_already_archived_idempotent(
    client: TestClient,
    repo_mock: Any,
    make_jwt: Callable[..., str],
) -> None:
    """Already archived → 204 no-op (no fresh audit row)."""
    cat = _make_category(archived=True)
    repo_mock.get_by_id.return_value = cat
    repo_mock.archive.return_value = cat
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/admin/categories/{cat.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
