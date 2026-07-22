"""Tests for POST /api/v1/auth/platform-session (мост личности платформы).

Endpoint признаёт залогиненного на rehome.one юзера по платформенному `rh_token`
(тот же домен под /help). Флаг `PLATFORM_SESSION_ENABLED` по умолчанию off.
Платформенные вызовы (`PlatformClient`) мокаются — сети в unit-тестах нет.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

_ENDPOINT = "/api/v1/auth/platform-session"


def test_disabled_by_default_returns_anonymous(client: TestClient) -> None:
    """Флаг off (default) → всегда authenticated=false, даже с токеном."""
    resp = client.post(_ENDPOINT, headers={"X-RH-Token": "whatever"})
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is False


def test_no_token_returns_anonymous(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLATFORM_SESSION_ENABLED", "true")
    resp = client.post(_ENDPOINT)
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is False


def test_valid_rh_token_is_recognized(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLATFORM_SESSION_ENABLED", "true")

    class _FakeClient:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_me(self, rh_token: str) -> dict[str, Any] | None:
            return {
                "first_name": "Иван",
                "last_name": "Петров",
                "phone_number": "+79000000001",
            }

        async def get_onboarding_status(
            self, *, phone: str, role: str
        ) -> dict[str, Any] | None:
            return {"complete": True, "next_path": None}

    monkeypatch.setattr("src.api.platform.router.PlatformClient", _FakeClient)
    resp = client.post(_ENDPOINT, headers={"X-RH-Token": "valid"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is True
    assert body["display_name"] == "Иван Петров"
    assert body["onboarding_complete"] is True


def test_invalid_rh_token_returns_anonymous(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Платформа отвергла токен (get_me → None) → authenticated=false."""
    monkeypatch.setenv("PLATFORM_SESSION_ENABLED", "true")

    class _FakeClient:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...

        async def get_me(self, rh_token: str) -> dict[str, Any] | None:
            return None

        async def get_onboarding_status(
            self, *, phone: str, role: str
        ) -> dict[str, Any] | None:
            return None

    monkeypatch.setattr("src.api.platform.router.PlatformClient", _FakeClient)
    resp = client.post(_ENDPOINT, headers={"X-RH-Token": "bad"})
    assert resp.json()["authenticated"] is False
