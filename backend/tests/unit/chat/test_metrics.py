"""Unit tests для chat Prometheus metrics (#179)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.chat.metrics import SESSIONS_CREATED_TOTAL
from src.api.chat.models import ChatSession
from src.api.chat.repository import ChatRepository, get_chat_repository
from src.api.main import app


def _make_session(user_id: object = None) -> ChatSession:
    s = ChatSession()
    s.id = uuid4()
    s.user_id = user_id  # type: ignore[assignment]
    s.session_token = uuid4()
    s.scope = "tenant" if user_id is not None else "guest"
    s.context = {}
    s.created_at = datetime.now(UTC)
    s.expires_at = datetime.now(UTC) + timedelta(days=1)
    s.deleted_at = None
    return s


def _counter_value(counter: Any, **labels: str) -> float:
    return float(counter.labels(**labels)._value.get())


@pytest.fixture
def override_create(monkeypatch: pytest.MonkeyPatch) -> Iterator[AsyncMock]:
    create_mock = AsyncMock()
    repo = ChatRepository.__new__(ChatRepository)
    repo.create_session = create_mock  # type: ignore[method-assign]
    app.dependency_overrides[get_chat_repository] = lambda: repo
    yield create_mock
    app.dependency_overrides.pop(get_chat_repository, None)


def test_create_session_increments_sessions_counter_guest_scope(
    client: TestClient,
    override_create: AsyncMock,
) -> None:
    """Anon → SESSIONS_CREATED_TOTAL{scope=guest} +1."""
    override_create.return_value = _make_session(user_id=None)

    before = _counter_value(SESSIONS_CREATED_TOTAL, scope="guest")
    resp = client.post("/api/v1/chat/sessions")
    assert resp.status_code == 201
    after = _counter_value(SESSIONS_CREATED_TOTAL, scope="guest")
    assert after - before == 1.0
