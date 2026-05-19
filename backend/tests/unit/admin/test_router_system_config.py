"""Unit tests для GET /api/v1/admin/system-config (#229)."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.admin.system_config import build_system_config
from src.api.config import Settings, get_settings
from src.api.main import app


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate(overrides)


# ---------------------------------------------------------------------------
# Pure-function build_system_config


def test_build_returns_complete_shape() -> None:
    cfg = build_system_config(_settings())
    # 5 sub-blocks per OpenAPI §SystemConfig.
    assert cfg.rate_limits is not None
    assert cfg.feature_flags is not None
    assert cfg.llm_config is not None
    assert cfg.moderation is not None
    assert cfg.webhooks is not None


def test_llm_config_uses_settings() -> None:
    cfg = build_system_config(_settings(LLM_PROVIDER="gigachat", LLM_MAX_TOKENS=2048))
    assert cfg.llm_config.active_provider == "gigachat"
    assert cfg.llm_config.max_context_tokens == 2048
    # Fallback / ab_test / temperature — null until multi-provider routing lands.
    assert cfg.llm_config.fallback_provider is None
    assert cfg.llm_config.ab_test_split_percent is None
    assert cfg.llm_config.temperature is None


def test_feature_flags_reflect_settings() -> None:
    cfg = build_system_config(
        _settings(
            RAG_ENABLED=True,
            METRICS_ENABLED=True,
            WEBHOOK_WORKER_ENABLED=False,
            MINIO_ENABLED=True,
            RERANK_ENABLED=False,
        )
    )
    assert cfg.feature_flags == {
        "rag": True,
        "metrics_endpoint": True,
        "webhook_worker": False,
        "minio": True,
        "rerank": False,
    }


def test_webhooks_block_from_settings() -> None:
    cfg = build_system_config(
        _settings(WEBHOOK_MAX_ATTEMPTS=7, WEBHOOK_DELIVERY_TIMEOUT_SECONDS=15.0)
    )
    assert cfg.webhooks.max_retries == 7
    assert cfg.webhooks.timeout_seconds == 15.0


def test_rate_limits_all_null() -> None:
    """Rate-limit config ещё не landed → все поля null."""
    cfg = build_system_config(_settings())
    rl = cfg.rate_limits
    assert rl.guest_per_minute is None
    assert rl.user_per_minute is None
    assert rl.m2m_per_minute is None
    assert rl.chat_messages_per_5min is None


def test_moderation_all_null() -> None:
    """Moderation feature не landed → null / empty."""
    cfg = build_system_config(_settings())
    assert cfg.moderation.auto_publish_threshold is None
    assert cfg.moderation.require_review_for_categories == []


# ---------------------------------------------------------------------------
# Router endpoint


def test_anon_returns_401(client: TestClient) -> None:
    resp = client.get("/api/v1/admin/system-config")
    assert resp.status_code == 401


def test_tenant_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/system-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_staff_support_alone_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    """staff_support (STAFF без LEGAL) → 403."""
    token = make_jwt(roles=["staff_support"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/system-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_staff_admin_returns_200(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/system-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "rate_limits",
        "feature_flags",
        "llm_config",
        "moderation",
        "webhooks",
    }


def test_response_shows_current_llm_provider(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_PROVIDER env → llm_config.active_provider."""
    monkeypatch.setenv("LLM_PROVIDER", "yandex_gpt")
    app.dependency_overrides[get_settings] = lambda: Settings()
    try:
        token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
        resp = client.get(
            "/api/v1/admin/system-config",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = resp.json()
        assert body["llm_config"]["active_provider"] == "yandex_gpt"
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_response_feature_flags_have_stable_keys(
    client: TestClient, make_jwt: Callable[..., str]
) -> None:
    """Admin UI расчитывает на стабильный список keys."""
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/system-config",
        headers={"Authorization": f"Bearer {token}"},
    )
    flags = resp.json()["feature_flags"]
    assert set(flags.keys()) == {"rag", "metrics_endpoint", "webhook_worker", "minio", "rerank"}
