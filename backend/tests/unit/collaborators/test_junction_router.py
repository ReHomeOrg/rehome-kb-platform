"""Router tests для /premises/{id}/collaborators (Slice 5)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.collaborators.junction_repository import (
    PremisesCollaboratorRepository,
    get_premises_collaborator_repository,
)
from src.api.collaborators.models import Collaborator, PremisesCollaborator
from src.api.db import get_session
from src.api.main import app


def _collab(group: str = "D", type_: str = "management_company") -> Collaborator:
    c = Collaborator()
    c.id = uuid4()
    c.brand_name = "УК Test"
    c.type = type_
    c.financial_group = group
    c.status = "ACTIVE"
    c.service_area = "Москва"
    c.working_hours = "24/7"
    c.website = None
    c.rating = None
    return c


def _junction(pid: Any, cid: Any, role: str = "default_uk") -> PremisesCollaborator:
    pc = PremisesCollaborator()
    pc.id = uuid4()
    pc.premises_id = pid
    pc.collaborator_id = cid
    pc.role = role
    pc.priority = 1
    pc.notes = None
    pc.assigned_at = datetime(2026, 5, 17, tzinfo=UTC)
    pc.assigned_by = "staff"
    return pc


@pytest.fixture
def list_mock() -> AsyncMock:
    return AsyncMock(return_value=[])


@pytest.fixture
def assign_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def remove_mock() -> AsyncMock:
    return AsyncMock(return_value=0)


@pytest.fixture
def override_junction_repo(
    list_mock: AsyncMock, assign_mock: AsyncMock, remove_mock: AsyncMock
) -> Iterator[dict[str, AsyncMock]]:
    repo = PremisesCollaboratorRepository.__new__(PremisesCollaboratorRepository)
    repo.list_for_premises = list_mock  # type: ignore[method-assign]
    repo.assign = assign_mock  # type: ignore[method-assign]
    repo.remove = remove_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_premises_collaborator_repository] = lambda: repo
    yield {"list": list_mock, "assign": assign_mock, "remove": remove_mock}
    app.dependency_overrides.pop(get_premises_collaborator_repository, None)


@pytest.fixture
def audit_mock() -> Iterator[AsyncMock]:
    record = AsyncMock()
    fake = MagicMock(spec=AuditRepository)
    fake.record = record
    app.dependency_overrides[get_audit_repository] = lambda: fake
    yield record
    app.dependency_overrides.pop(get_audit_repository, None)


@pytest.fixture
def session_mock() -> Iterator[MagicMock]:
    fake = MagicMock()
    fake.commit = AsyncMock()

    async def _yield() -> Any:
        yield fake

    app.dependency_overrides[get_session] = _yield
    yield fake
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# GET /premises/{id}/collaborators


def test_list_returns_200_for_guest(
    client: TestClient, override_junction_repo: dict[str, AsyncMock]
) -> None:
    resp = client.get(f"/api/v1/premises/{uuid4()}/collaborators")
    assert resp.status_code == 200
    assert resp.json() == {"data": []}


def test_list_renders_junction_rows_with_inline_collaborator(
    client: TestClient,
    override_junction_repo: dict[str, AsyncMock],
) -> None:
    pid = uuid4()
    c = _collab("D")
    pc = _junction(pid, c.id, role="default_uk")
    override_junction_repo["list"].return_value = [(pc, c)]
    resp = client.get(f"/api/v1/premises/{pid}/collaborators")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    row = body["data"][0]
    assert row["role"] == "default_uk"
    assert row["priority"] == 1
    assert row["collaborator"]["type"] == "management_company"
    assert row["collaborator"]["financial_group"] == "D"


def test_list_guest_passes_d_only_group_filter(
    client: TestClient, override_junction_repo: dict[str, AsyncMock]
) -> None:
    pid = uuid4()
    client.get(f"/api/v1/premises/{pid}/collaborators")
    kwargs = override_junction_repo["list"].call_args.kwargs
    assert kwargs["allowed_groups"] == frozenset({"D"})


def test_list_staff_passes_all_groups(
    client: TestClient,
    override_junction_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    pid = uuid4()
    client.get(
        f"/api/v1/premises/{pid}/collaborators",
        headers={"Authorization": f"Bearer {token}"},
    )
    kwargs = override_junction_repo["list"].call_args.kwargs
    assert kwargs["allowed_groups"] == frozenset({"A", "B", "C", "D"})


# ---------------------------------------------------------------------------
# POST /premises/{id}/collaborators


def test_assign_anon_returns_403(
    client: TestClient, override_junction_repo: dict[str, AsyncMock]
) -> None:
    resp = client.post(
        f"/api/v1/premises/{uuid4()}/collaborators",
        json={"collaborator_id": str(uuid4()), "role": "default_uk"},
    )
    assert resp.status_code == 403


def test_assign_staff_201_with_audit(
    client: TestClient,
    override_junction_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    pid = uuid4()
    c = _collab("B", type_="cleaning")
    pc = _junction(pid, c.id, role="cleaner")
    pc.priority = 2
    override_junction_repo["assign"].return_value = pc
    override_junction_repo["list"].return_value = [(pc, c)]
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/premises/{pid}/collaborators",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "collaborator_id": str(c.id),
            "role": "cleaner",
            "priority": 2,
            "notes": "Понедельник, среда, пятница",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["role"] == "cleaner"
    assert body["priority"] == 2
    audit_mock.assert_awaited_once()
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["action"] == "premises.collaborator.assigned"
    assert kwargs["metadata"]["role"] == "cleaner"
    assert kwargs["metadata"]["priority"] == 2


def test_assign_duplicate_returns_409(
    client: TestClient,
    override_junction_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    """Repository returns None при IntegrityError → 409."""
    override_junction_repo["assign"].return_value = None
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/premises/{uuid4()}/collaborators",
        headers={"Authorization": f"Bearer {token}"},
        json={"collaborator_id": str(uuid4()), "role": "default_uk"},
    )
    assert resp.status_code == 409
    audit_mock.assert_not_awaited()


def test_assign_invalid_priority_returns_422(
    client: TestClient,
    override_junction_repo: dict[str, AsyncMock],
    make_jwt: Callable[..., str],
) -> None:
    """priority >= 1 required (ge=1 в Pydantic)."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/premises/{uuid4()}/collaborators",
        headers={"Authorization": f"Bearer {token}"},
        json={"collaborator_id": str(uuid4()), "role": "x", "priority": 0},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /premises/{id}/collaborators/{collaborator_id}


def test_unassign_anon_returns_403(
    client: TestClient, override_junction_repo: dict[str, AsyncMock]
) -> None:
    resp = client.delete(f"/api/v1/premises/{uuid4()}/collaborators/{uuid4()}")
    assert resp.status_code == 403


def test_unassign_returns_204_on_success(
    client: TestClient,
    override_junction_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    override_junction_repo["remove"].return_value = 2
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/premises/{uuid4()}/collaborators/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["metadata"]["rows_deleted"] == 2


def test_unassign_specific_role_passes_query(
    client: TestClient,
    override_junction_repo: dict[str, AsyncMock],
    audit_mock: AsyncMock,
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    override_junction_repo["remove"].return_value = 1
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/premises/{uuid4()}/collaborators/{uuid4()}?role=emergency_water",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    assert override_junction_repo["remove"].call_args.kwargs["role"] == "emergency_water"


def test_unassign_returns_404_when_zero_deleted(
    client: TestClient,
    override_junction_repo: dict[str, AsyncMock],
    session_mock: MagicMock,
    make_jwt: Callable[..., str],
) -> None:
    override_junction_repo["remove"].return_value = 0
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.delete(
        f"/api/v1/premises/{uuid4()}/collaborators/{uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
