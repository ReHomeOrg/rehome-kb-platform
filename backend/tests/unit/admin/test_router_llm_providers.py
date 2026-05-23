"""Unit tests для GET /api/v1/admin/llm/providers (#228)."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.admin.llm_providers import (
    KNOWN_LLM_PROVIDER_IDS,
    build_provider_catalog,
)
from src.api.config import Settings, get_settings
from src.api.main import app

# ---------------------------------------------------------------------------
# Pure-function: build_provider_catalog


def _settings(**overrides: object) -> Settings:
    """Build Settings with overrides; default values per src/api/config.py."""
    return Settings.model_validate(overrides)


def test_catalog_returns_4_providers() -> None:
    catalog = build_provider_catalog(_settings())
    assert len(catalog) == 4
    ids = {p.id for p in catalog}
    assert ids == {"mock", "vllm", "gigachat", "yandex_gpt"}


def test_known_provider_ids_matches_catalog() -> None:
    """`KNOWN_LLM_PROVIDER_IDS` — single source of truth для validation;
    должен совпадать с IDs catalog'а (drift guard)."""
    catalog = build_provider_catalog(_settings())
    assert {p.id for p in catalog} == KNOWN_LLM_PROVIDER_IDS


def test_catalog_marks_current_provider() -> None:
    """Settings.llm_provider='gigachat' → только gigachat имеет is_current=True."""
    catalog = build_provider_catalog(_settings(LLM_PROVIDER="gigachat"))
    current = [p for p in catalog if p.is_current]
    assert len(current) == 1
    assert current[0].id == "gigachat"


def test_catalog_no_provider_match_all_inactive() -> None:
    """Unknown LLM_PROVIDER → все is_current=False (no crash)."""
    catalog = build_provider_catalog(_settings(LLM_PROVIDER="unknown"))
    assert all(not p.is_current for p in catalog)


def test_catalog_uses_settings_model_fields() -> None:
    """`model` поле берётся из Settings, не hardcoded."""
    catalog = build_provider_catalog(
        _settings(
            LLM_GIGACHAT_MODEL="GigaChat-Pro",
            LLM_YANDEX_MODEL="yandexgpt",
            LLM_YANDEX_MODEL_VERSION="rc",
        )
    )
    gigachat = next(p for p in catalog if p.id == "gigachat")
    yandex = next(p for p in catalog if p.id == "yandex_gpt")
    assert gigachat.model == "GigaChat-Pro"
    # YandexGPT model — composite `model/version`.
    assert yandex.model == "yandexgpt/rc"


def test_catalog_vendor_labels() -> None:
    catalog = build_provider_catalog(_settings())
    vendors = {p.id: p.vendor for p in catalog}
    assert vendors["gigachat"] == "sber"
    assert vendors["yandex_gpt"] == "yandex"
    assert vendors["mock"] == "rehome-internal"
    assert vendors["vllm"] == "rehome-internal"


def test_catalog_status_is_experimental_for_mock_and_vllm() -> None:
    catalog = build_provider_catalog(_settings())
    by_id = {p.id: p for p in catalog}
    assert by_id["mock"].status == "EXPERIMENTAL"
    assert by_id["vllm"].status == "EXPERIMENTAL"
    assert by_id["gigachat"].status == "ACTIVE"
    assert by_id["yandex_gpt"].status == "ACTIVE"


def test_catalog_cost_fields_are_none() -> None:
    """`cost_per_1m_*_tokens_rub` — null в MVP (no authoritative source)."""
    catalog = build_provider_catalog(_settings())
    for p in catalog:
        assert p.cost_per_1m_input_tokens_rub is None
        assert p.cost_per_1m_output_tokens_rub is None


def test_catalog_health_fields_are_none() -> None:
    """health_status / last_health_check — null без poller'а."""
    catalog = build_provider_catalog(_settings())
    for p in catalog:
        assert p.health_status is None
        assert p.last_health_check is None


# ---------------------------------------------------------------------------
# Router endpoint


def test_anon_returns_401(client: TestClient) -> None:
    resp = client.get("/api/v1/admin/llm/providers")
    assert resp.status_code == 401


def test_tenant_returns_403(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["tenant"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/llm/providers",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_staff_admin_returns_4_providers(client: TestClient, make_jwt: Callable[..., str]) -> None:
    token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
    resp = client.get(
        "/api/v1/admin/llm/providers",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {p["id"] for p in body["data"]}
    assert ids == {"mock", "vllm", "gigachat", "yandex_gpt"}


def test_response_marks_current_provider_per_env(
    client: TestClient,
    make_jwt: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_PROVIDER env='yandex_gpt' → yandex_gpt.is_current=true в response."""
    monkeypatch.setenv("LLM_PROVIDER", "yandex_gpt")
    # Override get_settings dependency to pick up env change.
    app.dependency_overrides[get_settings] = lambda: Settings()
    try:
        token = make_jwt(roles=["staff_admin"], sub=str(uuid4()))
        resp = client.get(
            "/api/v1/admin/llm/providers",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = resp.json()
        current = [p for p in body["data"] if p["is_current"]]
        assert len(current) == 1
        assert current[0]["id"] == "yandex_gpt"
    finally:
        app.dependency_overrides.pop(get_settings, None)
