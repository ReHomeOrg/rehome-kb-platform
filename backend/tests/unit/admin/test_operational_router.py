"""Unit tests для /admin/cache, /admin/reindex, /admin/tasks/{id} (#238)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.admin.tasks_models import AdminTask
from src.api.admin.tasks_repository import (
    AdminTaskRepository,
    get_admin_task_repository,
)
from src.api.audit.repository import get_audit_repository
from src.api.main import app


def _make_task(
    *,
    type_: str = "reindex",
    status: str = "PENDING",
    actor_sub: str = "admin-uuid",
    progress: int = 0,
    completed_at: datetime | None = None,
    error: str | None = None,
    params: dict[str, Any] | None = None,
) -> AdminTask:
    row = AdminTask(
        type=type_,
        status=status,
        actor_sub=actor_sub,
        progress_percent=progress,
        params=params or {},
        error=error,
    )
    row.id = uuid4()
    row.created_at = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    row.completed_at = completed_at
    return row


@pytest.fixture
def task_repo_mock() -> Iterator[dict[str, AsyncMock]]:
    """Override AdminTaskRepository — мы тестируем routers, не storage."""
    create = AsyncMock()
    get_task = AsyncMock()
    mark_running = AsyncMock()
    mark_completed = AsyncMock()
    mark_failed = AsyncMock()

    class _FakeRepo:
        def __init__(self) -> None:
            self.create = create
            self.get = get_task
            self.mark_running = mark_running
            self.mark_completed = mark_completed
            self.mark_failed = mark_failed

    app.dependency_overrides[get_admin_task_repository] = lambda: _FakeRepo()
    yield {
        "create": create,
        "get": get_task,
        "mark_running": mark_running,
        "mark_completed": mark_completed,
        "mark_failed": mark_failed,
    }
    app.dependency_overrides.pop(get_admin_task_repository, None)


@pytest.fixture
def audit_repo_mock() -> Iterator[AsyncMock]:
    record = AsyncMock()

    class _FakeRepo:
        def __init__(self) -> None:
            self.record = record

    app.dependency_overrides[get_audit_repository] = lambda: _FakeRepo()
    yield record
    app.dependency_overrides.pop(get_audit_repository, None)


# ---------------------------------------------------------------------------
# DELETE /admin/cache


def test_cache_anon_returns_401(client: TestClient) -> None:
    resp = client.delete("/api/v1/admin/cache")
    assert resp.status_code == 401


def test_cache_tenant_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.delete("/api/v1/admin/cache", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_cache_staff_support_returns_403(
    client: TestClient,
    make_jwt: Callable[..., str],
) -> None:
    """staff_support имеет STAFF, не имеет LEGAL → 403."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.delete("/api/v1/admin/cache", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_cache_staff_admin_default_scope(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_repo_mock: AsyncMock,
) -> None:
    """default scope='all' принимается; возвращает 202."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete("/api/v1/admin/cache", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["scope"] == "all"
    audit_repo_mock.assert_awaited_once()
    assert audit_repo_mock.call_args.kwargs["action"] == "admin.cache.invalidated"


def test_cache_staff_admin_custom_scope(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_repo_mock: AsyncMock,
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        "/api/v1/admin/cache?scope=articles",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["scope"] == "articles"


def test_cache_invalid_scope_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    audit_repo_mock: AsyncMock,
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        "/api/v1/admin/cache?scope=unknown",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /admin/reindex


def test_reindex_anon_returns_401(client: TestClient) -> None:
    resp = client.post("/api/v1/admin/reindex")
    assert resp.status_code == 401


def test_reindex_tenant_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post("/api/v1/admin/reindex", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_reindex_staff_admin_default_scope(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    task = _make_task(status="PENDING")
    task_repo_mock["create"].return_value = task

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/reindex",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["task_id"] == str(task.id)
    # Lifecycle: create → mark_running → mark_completed.
    task_repo_mock["create"].assert_awaited_once()
    assert task_repo_mock["create"].call_args.kwargs["type_"] == "reindex"
    assert task_repo_mock["create"].call_args.kwargs["params"] == {"scope": "all"}
    task_repo_mock["mark_running"].assert_awaited_once_with(task.id)
    task_repo_mock["mark_completed"].assert_awaited_once_with(task.id)
    # Audit trail.
    audit_repo_mock.assert_awaited_once()
    assert audit_repo_mock.call_args.kwargs["action"] == "admin.reindex.triggered"


def test_reindex_with_explicit_scope(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    task = _make_task()
    task_repo_mock["create"].return_value = task

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/reindex",
        json={"scope": "articles"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    assert task_repo_mock["create"].call_args.kwargs["params"] == {"scope": "articles"}


def test_reindex_calls_indexer_for_articles_scope(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    """scope=articles → IndexerService.reindex_all_articles вызывается (#240)."""
    from unittest.mock import MagicMock

    from src.api.search.indexer import IndexerService, ReindexResult, get_indexer_service

    indexer = MagicMock(spec=IndexerService)
    indexer.reindex_all_articles = AsyncMock(
        return_value=ReindexResult(articles_processed=5, chunks_total=15, errors_total=0)
    )
    app.dependency_overrides[get_indexer_service] = lambda: indexer

    try:
        task = _make_task()
        task_repo_mock["create"].return_value = task

        token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
        resp = client.post(
            "/api/v1/admin/reindex",
            json={"scope": "articles"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202
        indexer.reindex_all_articles.assert_awaited_once()
        task_repo_mock["mark_completed"].assert_awaited_once_with(task.id)
        task_repo_mock["mark_failed"].assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_indexer_service, None)


def test_reindex_documents_scope_skips_indexer(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    """scope=documents — honest stub (no document indexer); task COMPLETED без indexer call."""
    from unittest.mock import MagicMock

    from src.api.search.indexer import IndexerService, get_indexer_service

    indexer = MagicMock(spec=IndexerService)
    indexer.reindex_all_articles = AsyncMock()
    app.dependency_overrides[get_indexer_service] = lambda: indexer

    try:
        task = _make_task()
        task_repo_mock["create"].return_value = task

        token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
        resp = client.post(
            "/api/v1/admin/reindex",
            json={"scope": "documents"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 202
        indexer.reindex_all_articles.assert_not_awaited()
        task_repo_mock["mark_completed"].assert_awaited_once_with(task.id)
    finally:
        app.dependency_overrides.pop(get_indexer_service, None)


def test_reindex_all_zero_processed_with_errors_returns_500(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
    audit_repo_mock: AsyncMock,
) -> None:
    """Catastrophic failure path: 0 processed + errors > 0 → 500 + mark_failed."""
    from unittest.mock import MagicMock

    from src.api.search.indexer import IndexerService, ReindexResult, get_indexer_service

    indexer = MagicMock(spec=IndexerService)
    indexer.reindex_all_articles = AsyncMock(
        return_value=ReindexResult(articles_processed=0, chunks_total=0, errors_total=3)
    )
    app.dependency_overrides[get_indexer_service] = lambda: indexer

    try:
        task = _make_task()
        task_repo_mock["create"].return_value = task

        token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
        resp = client.post(
            "/api/v1/admin/reindex",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 500
        task_repo_mock["mark_failed"].assert_awaited_once()
        task_repo_mock["mark_completed"].assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_indexer_service, None)


def test_reindex_invalid_scope_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/reindex",
        json={"scope": "users"},  # not in enum
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /admin/tasks/{task_id}


def test_get_task_anon_returns_401(client: TestClient) -> None:
    resp = client.get(f"/api/v1/admin/tasks/{uuid4()}")
    assert resp.status_code == 401


def test_get_task_tenant_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/tasks/{uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403


def test_get_task_not_found_returns_404(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    task_repo_mock["get"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/tasks/{uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


def test_get_task_pending_shape(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    task = _make_task(type_="reindex", status="PENDING", progress=0)
    task_repo_mock["get"].return_value = task

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/tasks/{task.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == str(task.id)
    assert body["type"] == "reindex"
    assert body["status"] == "PENDING"
    assert body["progress_percent"] == 0
    assert body["completed_at"] is None
    assert body["result_url"] is None
    assert body["error"] is None


def test_get_task_completed_shape(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    completed = datetime(2026, 5, 1, 12, 5, tzinfo=UTC)
    task = _make_task(
        type_="audit_log_export",
        status="COMPLETED",
        progress=100,
        completed_at=completed,
    )
    task_repo_mock["get"].return_value = task

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/tasks/{task.id}", headers={"Authorization": f"Bearer {token}"}
    )
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["progress_percent"] == 100
    assert body["completed_at"].startswith("2026-05-01T12:05:00")


def test_get_task_failed_shape(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    completed = datetime(2026, 5, 1, 12, 5, tzinfo=UTC)
    task = _make_task(
        type_="reindex",
        status="FAILED",
        completed_at=completed,
        error="OOM during index rebuild",
    )
    task_repo_mock["get"].return_value = task

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        f"/api/v1/admin/tasks/{task.id}", headers={"Authorization": f"Bearer {token}"}
    )
    body = resp.json()
    assert body["status"] == "FAILED"
    assert body["error"] == "OOM during index rebuild"


# ---------------------------------------------------------------------------
# Repository unit tests (pure logic)


def test_repo_create_rejects_unknown_type() -> None:
    """Defensive check — каллер не должен передавать произвольные строки."""
    import asyncio
    from unittest.mock import MagicMock

    repo = AdminTaskRepository(MagicMock())

    async def go() -> None:
        with pytest.raises(ValueError, match="Unknown task type"):
            await repo.create(type_="badtype", actor_sub="x")

    asyncio.run(go())


def test_repo_list_recent_rejects_unknown_type() -> None:
    import asyncio
    from unittest.mock import MagicMock

    repo = AdminTaskRepository(MagicMock())

    async def go() -> None:
        with pytest.raises(ValueError, match="Unknown task type"):
            await repo.list_recent(type_="badtype")

    asyncio.run(go())


def test_repo_list_recent_rejects_unknown_status() -> None:
    import asyncio
    from unittest.mock import MagicMock

    repo = AdminTaskRepository(MagicMock())

    async def go() -> None:
        with pytest.raises(ValueError, match="Unknown task statuses"):
            await repo.list_recent(statuses=("WEIRD",))

    asyncio.run(go())
