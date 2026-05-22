"""Unit tests для Idempotency-Key поверх POST /chat/sessions/{id}/escalate.

См. `src/api/chat/idempotency.py::process_chat_idempotency_key` для
семантики (replay при тот же body, 409 при mismatched body, anon flow
через `extract_chat_owner`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.chat.idempotency import _chat_actor_sub
from src.api.chat.models import ChatEscalation, ChatSession
from src.api.chat.repository import ChatRepository, get_chat_repository
from src.api.idempotency.models import IdempotencyKey
from src.api.idempotency.repository import (
    IdempotencyKeyRepository,
    get_idempotency_repository,
)
from src.api.main import app

# ---------------------------------------------------------------------------
# Pure: _chat_actor_sub


def test_chat_actor_sub_authenticated_uses_user_id() -> None:
    user_id = uuid4()
    assert _chat_actor_sub(user_id, None) == str(user_id)


def test_chat_actor_sub_anon_uses_token_prefix() -> None:
    token = uuid4()
    actor = _chat_actor_sub(None, token)
    assert actor is not None
    assert actor.startswith("anon:")
    # Префикс — ANON_ACTOR_TOKEN_PREFIX_LEN символов (8 в audit/actions.py).
    assert len(actor) == len("anon:") + 8


def test_chat_actor_sub_no_identifier_returns_none() -> None:
    """Ни user_id, ни session_token → idempotency не активируется."""
    assert _chat_actor_sub(None, None) is None


def test_chat_actor_sub_auth_takes_precedence_over_anon_token() -> None:
    """Если есть оба — auth user_id выигрывает."""
    user_id = uuid4()
    token = uuid4()
    actor = _chat_actor_sub(user_id, token)
    assert actor == str(user_id)
    assert not actor.startswith("anon:")


# ---------------------------------------------------------------------------
# Router integration


def _make_session() -> ChatSession:
    s = ChatSession()
    s.id = uuid4()
    s.user_id = uuid4()
    s.session_token = uuid4()
    s.scope = "tenant"
    s.context = {}
    s.created_at = datetime.now(UTC)
    s.expires_at = datetime.now(UTC) + timedelta(days=1)
    s.deleted_at = None
    return s


def _make_escalation(session_id: object, priority: str = "normal") -> ChatEscalation:
    e = ChatEscalation()
    e.id = uuid4()
    e.session_id = session_id  # type: ignore[assignment]
    e.requested_by_user_id = uuid4()
    e.reason = None
    e.priority = priority
    e.status = "pending"
    e.requested_at = datetime.now(UTC)
    return e


def _make_fake_idempo_repo() -> Any:
    repo = MagicMock(spec=IdempotencyKeyRepository)
    repo.acquire_lock = AsyncMock()
    repo.get = AsyncMock(return_value=None)
    repo.save = AsyncMock()
    return repo


@pytest.fixture
def create_escalation_mock() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def override_repo(create_escalation_mock: AsyncMock) -> Iterator[AsyncMock]:
    repo = ChatRepository.__new__(ChatRepository)
    repo.create_escalation = create_escalation_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_chat_repository] = lambda: repo
    yield create_escalation_mock
    app.dependency_overrides.pop(get_chat_repository, None)


@pytest.fixture
def override_idempo() -> Iterator[Any]:
    repo = _make_fake_idempo_repo()
    app.dependency_overrides[get_idempotency_repository] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_idempotency_repository, None)


def test_no_key_is_noop_for_anon(
    client: TestClient,
    override_repo: AsyncMock,
    override_idempo: Any,
) -> None:
    """Без Idempotency-Key — анон flow работает как раньше, без repo взаимодействия."""
    session = _make_session()
    override_repo.return_value = _make_escalation(session.id)

    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        headers={"X-Chat-Session-Token": str(session.session_token)},
    )
    assert resp.status_code == 201
    override_idempo.acquire_lock.assert_not_awaited()
    override_idempo.save.assert_not_awaited()


def test_authenticated_first_call_saves_response(
    client: TestClient,
    override_repo: AsyncMock,
    override_idempo: Any,
    make_jwt: Callable[..., str],
) -> None:
    """С Idempotency-Key + authenticated — первый POST вызывает repo.save."""
    session = _make_session()
    esc = _make_escalation(session.id, priority="normal")
    override_repo.return_value = esc

    key = str(uuid4())
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )
    assert resp.status_code == 201
    override_idempo.acquire_lock.assert_awaited_once()
    override_idempo.save.assert_awaited_once()
    save_kwargs = override_idempo.save.call_args.kwargs
    assert save_kwargs["key"] == key
    assert save_kwargs["response_status"] == 201
    assert save_kwargs["response_body"]["ticket_id"] == str(esc.id)


def test_authenticated_replay_returns_cached_response(
    client: TestClient,
    override_repo: AsyncMock,
    override_idempo: Any,
    make_jwt: Callable[..., str],
) -> None:
    """Cached IdempotencyKey row с тем же body_hash → replay,
    create_escalation НЕ вызывается."""
    session = _make_session()

    cached_ticket_id = uuid4()
    existing = IdempotencyKey(
        key="ignored",
        request_path=f"/api/v1/chat/sessions/{session.id}/escalate",
        actor_sub="ignored",
        # sha256(b"") — empty body, как когда POST без JSON.
        request_body_hash=("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
        response_status=201,
        response_body={"ticket_id": str(cached_ticket_id), "estimated_response_time_minutes": 30},
        response_headers={},
    )
    override_idempo.get = AsyncMock(return_value=existing)

    key = str(uuid4())
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["ticket_id"] == str(cached_ticket_id)
    # create_escalation НЕ вызвалась — это replay.
    override_repo.assert_not_awaited()


def test_anon_first_call_saves_with_anon_actor_sub(
    client: TestClient,
    override_repo: AsyncMock,
    override_idempo: Any,
) -> None:
    """Anon flow + Idempotency-Key → actor_sub = `anon:<token-prefix>`."""
    session = _make_session()
    esc = _make_escalation(session.id)
    override_repo.return_value = esc

    key = str(uuid4())
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        headers={
            "X-Chat-Session-Token": str(session.session_token),
            "Idempotency-Key": key,
        },
    )
    assert resp.status_code == 201
    override_idempo.save.assert_awaited_once()
    save_kwargs = override_idempo.save.call_args.kwargs
    assert save_kwargs["actor_sub"].startswith("anon:")


def test_replay_skips_create_escalation_call_anon(
    client: TestClient,
    override_repo: AsyncMock,
    override_idempo: Any,
) -> None:
    """Anon replay — create_escalation НЕ вызывается."""
    session = _make_session()
    cached_id = uuid4()
    existing = IdempotencyKey(
        key="ignored",
        request_path=f"/api/v1/chat/sessions/{session.id}/escalate",
        actor_sub="ignored",
        request_body_hash=("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
        response_status=201,
        response_body={"ticket_id": str(cached_id), "estimated_response_time_minutes": 30},
        response_headers={},
    )
    override_idempo.get = AsyncMock(return_value=existing)

    key = str(uuid4())
    resp = client.post(
        f"/api/v1/chat/sessions/{session.id}/escalate",
        headers={
            "X-Chat-Session-Token": str(session.session_token),
            "Idempotency-Key": key,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["ticket_id"] == str(cached_id)
    override_repo.assert_not_awaited()


def test_different_body_with_same_key_returns_409(
    client: TestClient,
    override_repo: AsyncMock,
    override_idempo: Any,
    make_jwt: Callable[..., str],
) -> None:
    """Same key, другой body → 409 (Stripe pattern)."""
    existing = IdempotencyKey(
        key="ignored",
        request_path="/x",
        actor_sub="ignored",
        # Hash отличается от того, который посчитает request middleware.
        request_body_hash="0" * 64,
        response_status=201,
        response_body={"ticket_id": str(uuid4()), "estimated_response_time_minutes": 30},
        response_headers={},
    )
    override_idempo.get = AsyncMock(return_value=existing)

    key = str(uuid4())
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/escalate",
        json={"priority": "high"},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key},
    )
    assert resp.status_code == 409
    # create_escalation не дёргается — 409 raises ДО business logic.
    override_repo.assert_not_awaited()


def test_invalid_uuid_key_returns_422(
    client: TestClient,
    override_repo: AsyncMock,
    override_idempo: Any,
    make_jwt: Callable[..., str],
) -> None:
    """Idempotency-Key не UUID → 422 (как admin endpoints)."""
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.post(
        f"/api/v1/chat/sessions/{uuid4()}/escalate",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "not-a-uuid"},
    )
    assert resp.status_code == 422
