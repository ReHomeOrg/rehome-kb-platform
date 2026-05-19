"""Tests для collaborator.* webhook event emitters (#225, ТЗ §5.1).

7 lifecycle event'ов wired:
- collaborator.created (POST /collaborators)
- collaborator.activated (POST /collaborators/{id}/activate)
- collaborator.suspended (POST /collaborators/{id}/suspend)
- collaborator.archived (DELETE /collaborators/{id})
- collaborator.review.posted (POST /collaborators/{id}/reviews) — отдельный
  тест-файл (другой router).
- collaborator.portal_access.changed (PUT /collaborators/{id}/portal-access)
- collaborator.onboarding.submitted (POST /collaborators/onboarding)
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.audit.repository import AuditRepository, get_audit_repository
from src.api.collaborators.models import Collaborator
from src.api.collaborators.repository import (
    CollaboratorRepository,
    get_collaborator_repository,
)
from src.api.db import get_session
from src.api.main import app
from src.api.webhooks.dispatcher import (
    WebhookEventDispatcher,
    get_webhook_event_dispatcher,
)


def _make_collab(**over: Any) -> Collaborator:
    c = Collaborator()
    c.id = uuid4()
    c.name = "Test"
    c.brand_name = None
    c.type = "cleaning"
    c.financial_group = "B"
    c.status = "DRAFT"
    c.legal_entity_type = None
    c.inn = None
    c.ogrn = None
    c.kpp = None
    c.service_area = "Москва"
    c.working_hours = None
    c.website = None
    c.responsible_internal = "ivanov.i"
    c.contract_document_id = uuid4()
    c.fallback_collaborator_id = None
    c.rating = None
    c.contacts = []
    c.financial_terms = {}
    c.api_integration = {}
    c.sla = {}
    c.counterparty_check = {"result": "CLEAN"}
    c.onboarding_source = "staff_invite"
    c.portal_access_level = "NONE"
    c.portal_access_history = []
    c.audit_log = []
    c.created_at = datetime(2026, 5, 18, tzinfo=UTC)
    c.updated_at = datetime(2026, 5, 18, tzinfo=UTC)
    for k, v in over.items():
        setattr(c, k, v)
    return c


@pytest.fixture
def collab_dispatch_mock() -> Iterator[AsyncMock]:
    """Track webhook dispatch calls."""
    dispatch = AsyncMock(return_value=1)
    fake = MagicMock(spec=WebhookEventDispatcher)
    fake.dispatch = dispatch
    app.dependency_overrides[get_webhook_event_dispatcher] = lambda: fake
    yield dispatch
    app.dependency_overrides.pop(get_webhook_event_dispatcher, None)


@pytest.fixture
def collab_repo_mock() -> Iterator[dict[str, AsyncMock]]:
    """Mock CollaboratorRepository — passthrough creates/updates/archives."""
    create_mock = AsyncMock()
    get_mock = AsyncMock(return_value=None)
    update_mock = AsyncMock()
    archive_mock = AsyncMock()

    async def _create_passthrough(c: Collaborator) -> Collaborator:
        c.id = c.id or uuid4()
        c.created_at = c.created_at or datetime(2026, 5, 18, tzinfo=UTC)
        c.updated_at = c.updated_at or datetime(2026, 5, 18, tzinfo=UTC)
        c.audit_log = c.audit_log if c.audit_log is not None else []
        c.portal_access_level = c.portal_access_level or "NONE"
        c.portal_access_history = c.portal_access_history or []
        c.onboarding_source = c.onboarding_source or "staff_invite"
        return c

    create_mock.side_effect = _create_passthrough

    async def _update_passthrough(c: Any, updates: Any, **_kw: Any) -> Any:
        for k, v in updates.items():
            setattr(c, k, v)
        return c

    update_mock.side_effect = _update_passthrough

    async def _archive_passthrough(c: Any) -> Any:
        c.status = "ARCHIVED"
        return c

    archive_mock.side_effect = _archive_passthrough

    repo = CollaboratorRepository.__new__(CollaboratorRepository)
    repo.create = create_mock  # type: ignore[method-assign]
    repo.get_by_id = get_mock  # type: ignore[method-assign]
    repo.update_fields = update_mock  # type: ignore[method-assign]
    repo.archive = archive_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_collaborator_repository] = lambda: repo

    audit_record = AsyncMock()
    audit = MagicMock(spec=AuditRepository)
    audit.record = audit_record
    app.dependency_overrides[get_audit_repository] = lambda: audit

    async def _session() -> Any:
        s = MagicMock()
        s.commit = AsyncMock()
        s.rollback = AsyncMock()
        yield s

    app.dependency_overrides[get_session] = _session

    yield {
        "create": create_mock,
        "get": get_mock,
        "update": update_mock,
        "archive": archive_mock,
        "audit_record": audit_record,
    }
    app.dependency_overrides.pop(get_collaborator_repository, None)
    app.dependency_overrides.pop(get_audit_repository, None)
    app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# POST /collaborators


def test_create_fires_collaborator_created(
    client: TestClient,
    collab_repo_mock: dict[str, AsyncMock],
    collab_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    token = make_jwt(roles=["staff_admin"], sub="admin-user-1")
    resp = client.post(
        "/api/v1/collaborators",
        json={"name": "ООО Чистый", "type": "cleaning", "service_area": "Москва"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    collab_dispatch_mock.assert_awaited_once()
    kwargs = collab_dispatch_mock.call_args.kwargs
    assert kwargs["event_type"] == "collaborator.created"
    payload = kwargs["payload"]
    assert payload["type"] == "cleaning"
    assert payload["financial_group"] == "B"
    assert "id" in payload


def test_create_uses_jwt_sub_for_audit_actor(
    client: TestClient,
    collab_repo_mock: dict[str, AsyncMock],
    collab_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """Regression: actor_sub в audit_log = JWT sub, не 'staff' хардкод."""
    token = make_jwt(roles=["staff_admin"], sub="admin-uuid-here")
    resp = client.post(
        "/api/v1/collaborators",
        json={"name": "ООО X", "type": "cleaning", "service_area": "СПб"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    audit_kwargs = collab_repo_mock["audit_record"].call_args.kwargs
    assert audit_kwargs["actor_sub"] == "admin-uuid-here"


# ---------------------------------------------------------------------------
# POST /collaborators/{id}/activate


def test_activate_fires_collaborator_activated(
    client: TestClient,
    collab_repo_mock: dict[str, AsyncMock],
    collab_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    c = _make_collab(status="DRAFT", financial_group="B")
    collab_repo_mock["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub="admin-1")
    resp = client.post(
        f"/api/v1/collaborators/{c.id}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    collab_dispatch_mock.assert_awaited_once()
    kwargs = collab_dispatch_mock.call_args.kwargs
    assert kwargs["event_type"] == "collaborator.activated"
    assert kwargs["payload"]["previous_status"] == "DRAFT"
    assert kwargs["payload"]["status"] == "ACTIVE"


def test_activate_with_invariant_violation_does_not_fire_webhook(
    client: TestClient,
    collab_repo_mock: dict[str, AsyncMock],
    collab_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """422 → state не изменился → no webhook."""
    c = _make_collab(status="DRAFT", financial_group="B", contract_document_id=None)
    collab_repo_mock["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub="admin-1")
    resp = client.post(
        f"/api/v1/collaborators/{c.id}/activate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    collab_dispatch_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /collaborators/{id}/suspend


def test_suspend_fires_collaborator_suspended(
    client: TestClient,
    collab_repo_mock: dict[str, AsyncMock],
    collab_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    c = _make_collab(status="ACTIVE")
    collab_repo_mock["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub="admin-1")
    resp = client.post(
        f"/api/v1/collaborators/{c.id}/suspend",
        json={"reason": "просрочка counterparty_check"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    collab_dispatch_mock.assert_awaited_once()
    kwargs = collab_dispatch_mock.call_args.kwargs
    assert kwargs["event_type"] == "collaborator.suspended"
    assert kwargs["payload"]["reason"] == "просрочка counterparty_check"
    assert kwargs["payload"]["previous_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# DELETE /collaborators/{id}


def test_archive_fires_collaborator_archived(
    client: TestClient,
    collab_repo_mock: dict[str, AsyncMock],
    collab_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    c = _make_collab(status="ACTIVE")
    collab_repo_mock["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub="admin-1")
    resp = client.delete(
        f"/api/v1/collaborators/{c.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204
    collab_dispatch_mock.assert_awaited_once()
    kwargs = collab_dispatch_mock.call_args.kwargs
    assert kwargs["event_type"] == "collaborator.archived"
    assert kwargs["payload"]["previous_status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# PUT /collaborators/{id}/portal-access


def test_portal_access_change_fires_event(
    client: TestClient,
    collab_repo_mock: dict[str, AsyncMock],
    collab_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    c = _make_collab(portal_access_level="LIGHT")
    collab_repo_mock["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub="admin-1")
    resp = client.put(
        f"/api/v1/collaborators/{c.id}/portal-access",
        json={"portal_access_level": "FULL", "reason": "оператор подтвердил"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    collab_dispatch_mock.assert_awaited_once()
    kwargs = collab_dispatch_mock.call_args.kwargs
    assert kwargs["event_type"] == "collaborator.portal_access.changed"
    payload = kwargs["payload"]
    assert payload["from"] == "LIGHT"
    assert payload["to"] == "FULL"


def test_portal_access_noop_does_not_fire_event(
    client: TestClient,
    collab_repo_mock: dict[str, AsyncMock],
    collab_dispatch_mock: AsyncMock,
    make_jwt: Callable[..., str],
) -> None:
    """current == target → no-op → no webhook."""
    c = _make_collab(portal_access_level="LIGHT")
    collab_repo_mock["get"].return_value = c
    token = make_jwt(roles=["staff_admin"], sub="admin-1")
    resp = client.put(
        f"/api/v1/collaborators/{c.id}/portal-access",
        json={"portal_access_level": "LIGHT"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    collab_dispatch_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /collaborators/onboarding (public, no auth)


def test_onboarding_fires_event(
    client: TestClient,
    collab_repo_mock: dict[str, AsyncMock],
    collab_dispatch_mock: AsyncMock,
) -> None:
    resp = client.post(
        "/api/v1/collaborators/onboarding",
        json={
            "name": "ИП Тест",
            "type": "cleaning",
            "legal_entity_type": "ip",
            "inn": "123456789012",
            "service_area": "Москва",
            "contact": {
                "name": "Иван",
                "phone": "+79991234567",
                "email": "test@example.com",
            },
            "portal_access_level_requested": "LIGHT",
        },
    )
    assert resp.status_code == 201, resp.text
    collab_dispatch_mock.assert_awaited_once()
    kwargs = collab_dispatch_mock.call_args.kwargs
    assert kwargs["event_type"] == "collaborator.onboarding.submitted"
    payload = kwargs["payload"]
    assert payload["status"] == "PENDING_REVIEW"
    assert payload["source"] == "form"
    assert payload["portal_access_requested"] == "LIGHT"
    # ПДн НЕ в payload (anti-leak invariant).
    assert "inn" not in payload
    assert "contact" not in payload
    assert "name" not in payload
