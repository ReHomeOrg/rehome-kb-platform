"""Unit tests для /admin/llm/eval-runs (#244)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.admin.eval_runs_schemas import EvalRunStartRequest
from src.api.admin.eval_runs_service import (
    ALLOWED_PROVIDERS,
    EvalRunsService,
    EvalRunValidationError,
)
from src.api.admin.tasks_models import AdminTask
from src.api.admin.tasks_repository import get_admin_task_repository
from src.api.main import app


def _make_task(
    *,
    status: str = "COMPLETED",
    params: dict[str, Any] | None = None,
) -> AdminTask:
    row = AdminTask(
        type="eval_run",
        status=status,
        actor_sub="admin-uuid",
        progress_percent=100 if status == "COMPLETED" else 0,
        params=params
        or {
            "providers": ["mock"],
            "test_set": "smoke",
            "pair_count": 10,
            "results": [
                {
                    "provider": "mock",
                    "composite_score": None,
                    "citation_accuracy": 0.5,
                    "avg_latency_ms": 100,
                    "cost_per_query_rub": 0.01,
                }
            ],
        },
    )
    row.id = uuid4()
    row.created_at = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    row.completed_at = datetime(2026, 5, 1, 12, 5, tzinfo=UTC) if status == "COMPLETED" else None
    return row


@pytest.fixture
def task_repo_mock() -> Iterator[dict[str, AsyncMock]]:
    create = AsyncMock()
    get_task = AsyncMock()
    mark_running = AsyncMock()
    mark_completed = AsyncMock()
    mark_failed = AsyncMock()
    list_recent = AsyncMock(return_value=[])

    class _FakeRepo:
        def __init__(self) -> None:
            self.create = create
            self.get = get_task
            self.mark_running = mark_running
            self.mark_completed = mark_completed
            self.mark_failed = mark_failed
            self.list_recent = list_recent

    app.dependency_overrides[get_admin_task_repository] = lambda: _FakeRepo()
    yield {
        "create": create,
        "get": get_task,
        "mark_running": mark_running,
        "mark_completed": mark_completed,
        "mark_failed": mark_failed,
        "list_recent": list_recent,
    }
    app.dependency_overrides.pop(get_admin_task_repository, None)


# ---------------------------------------------------------------------------
# Service-level validation (pure)


def test_allowed_providers_only_mock_currently() -> None:
    assert frozenset({"mock"}) == ALLOWED_PROVIDERS


def test_validate_rejects_unknown_provider() -> None:
    req = EvalRunStartRequest(providers=["gigachat"], test_set="smoke")
    with pytest.raises(EvalRunValidationError, match="Unsupported providers"):
        EvalRunsService._validate(req)


def test_validate_rejects_full_test_set() -> None:
    req = EvalRunStartRequest(providers=["mock"], test_set="full")
    with pytest.raises(EvalRunValidationError, match="full.*not yet supported"):
        EvalRunsService._validate(req)


def test_validate_rejects_custom_test_set() -> None:
    req = EvalRunStartRequest(providers=["mock"], test_set="custom")
    with pytest.raises(EvalRunValidationError, match="custom.*not yet supported"):
        EvalRunsService._validate(req)


def test_validate_accepts_mock_smoke() -> None:
    req = EvalRunStartRequest(providers=["mock"], test_set="smoke")
    EvalRunsService._validate(req)  # no exception


# ---------------------------------------------------------------------------
# POST /admin/llm/eval-runs RBAC + happy path


def test_post_anon_returns_401(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/admin/llm/eval-runs",
        json={"providers": ["mock"], "test_set": "smoke"},
    )
    assert resp.status_code == 401


def test_post_tenant_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/llm/eval-runs",
        json={"providers": ["mock"], "test_set": "smoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_post_staff_support_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    """staff_support не имеет LEGAL → 403."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/llm/eval-runs",
        json={"providers": ["mock"], "test_set": "smoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_post_unsupported_provider_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/llm/eval-runs",
        json={"providers": ["gigachat"], "test_set": "smoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_post_full_test_set_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/llm/eval-runs",
        json={"providers": ["mock"], "test_set": "full"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_post_missing_required_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/llm/eval-runs",
        json={},  # missing providers + test_set
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_post_empty_providers_returns_422(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    """min_length=1 на providers."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/llm/eval-runs",
        json={"providers": [], "test_set": "smoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_post_smoke_mock_returns_202(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    """Happy path: mock + smoke → 202 + run_id."""
    task = _make_task(status="PENDING")
    task_repo_mock["create"].return_value = task
    task_repo_mock["get"].return_value = task

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        "/api/v1/admin/llm/eval-runs",
        json={"providers": ["mock"], "test_set": "smoke"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["run_id"] == str(task.id)
    # Lifecycle: create → mark_running → mark_completed.
    task_repo_mock["create"].assert_awaited_once()
    create_kwargs = task_repo_mock["create"].call_args.kwargs
    assert create_kwargs["type_"] == "eval_run"
    assert create_kwargs["params"]["providers"] == ["mock"]
    assert create_kwargs["params"]["test_set"] == "smoke"
    task_repo_mock["mark_running"].assert_awaited_once_with(task.id)
    task_repo_mock["mark_completed"].assert_awaited_once_with(task.id)


# ---------------------------------------------------------------------------
# GET /admin/llm/eval-runs


def test_get_anon_returns_401(client: TestClient) -> None:
    resp = client.get("/api/v1/admin/llm/eval-runs")
    assert resp.status_code == 401


def test_get_tenant_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get("/api/v1/admin/llm/eval-runs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_get_returns_empty_list(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    task_repo_mock["list_recent"].return_value = []
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get("/api/v1/admin/llm/eval-runs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json() == {"data": []}


def test_get_returns_projected_runs(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    task = _make_task()
    task_repo_mock["list_recent"].return_value = [task]

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get("/api/v1/admin/llm/eval-runs", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    assert len(body["data"]) == 1
    run = body["data"][0]
    assert run["id"] == str(task.id)
    assert run["status"] == "COMPLETED"
    assert run["providers"] == ["mock"]
    assert run["test_set"] == "smoke"
    assert len(run["results"]) == 1
    assert run["results"][0]["provider"] == "mock"


def test_get_filters_by_provider(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    """?provider=mock returns runs где mock в providers list."""
    task_mock = _make_task(params={"providers": ["mock"], "test_set": "smoke", "results": []})
    task_other = _make_task(
        params={"providers": ["fake-other"], "test_set": "smoke", "results": []}
    )
    task_repo_mock["list_recent"].return_value = [task_mock, task_other]

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/llm/eval-runs?provider=mock",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["providers"] == ["mock"]


def test_get_status_mapping_pending_to_running(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    """admin_task.PENDING → EvalRun.RUNNING (sync MVP gap)."""
    task = _make_task(status="PENDING", params={"providers": ["mock"], "test_set": "smoke"})
    task_repo_mock["list_recent"].return_value = [task]

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get("/api/v1/admin/llm/eval-runs", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    assert body["data"][0]["status"] == "RUNNING"


def test_get_status_mapping_cancelled_to_failed(
    client: TestClient,
    make_jwt: Callable[..., str],
    task_repo_mock: dict[str, AsyncMock],
) -> None:
    """admin_task.CANCELLED → EvalRun.FAILED (OpenAPI не имеет CANCELLED)."""
    task = _make_task(status="CANCELLED", params={"providers": ["mock"], "test_set": "smoke"})
    task_repo_mock["list_recent"].return_value = [task]

    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get("/api/v1/admin/llm/eval-runs", headers={"Authorization": f"Bearer {token}"})
    body = resp.json()
    assert body["data"][0]["status"] == "FAILED"
