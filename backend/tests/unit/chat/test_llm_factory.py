"""Unit-тесты factory для LLMProvider (#65, singleton #350).

Singleton reset между тестами — в `tests/unit/chat/conftest.py`
(`_reset_llm_singleton` autouse fixture).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.api.chat.llm import MockProvider, get_llm_provider
from src.api.chat.llm import factory as factory_module
from src.api.chat.llm.factory import (
    build_llm_provider,
    close_llm_provider,
    init_llm_provider,
)
from src.api.config import Settings


def _settings(provider: str) -> Settings:
    return Settings(LLM_PROVIDER=provider)


# ---------------------------------------------------------------------------
# build_llm_provider — pure dispatch


def test_build_returns_mock_for_mock_setting() -> None:
    provider = build_llm_provider(_settings("mock"))
    assert isinstance(provider, MockProvider)


def test_build_case_insensitive() -> None:
    provider = build_llm_provider(_settings("MOCK"))
    assert isinstance(provider, MockProvider)


def test_build_unknown_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        build_llm_provider(_settings("openai"))


# ---------------------------------------------------------------------------
# init_llm_provider — singleton lifecycle


def test_init_returns_same_instance_on_repeat_call() -> None:
    """Idempotency: повторный init возвращает existing instance."""
    first = init_llm_provider(_settings("mock"))
    second = init_llm_provider(_settings("mock"))
    assert first is second


def test_get_lazy_inits_when_singleton_missing() -> None:
    """`get_llm_provider` без prior init → lazy bootstrap."""
    assert factory_module._llm_provider_instance is None
    provider = get_llm_provider(settings=_settings("mock"))
    assert isinstance(provider, MockProvider)
    assert factory_module._llm_provider_instance is provider


def test_get_returns_cached_singleton_after_init() -> None:
    """После init все get'ы возвращают тот же instance."""
    init_llm_provider(_settings("mock"))
    p1 = get_llm_provider(settings=_settings("mock"))
    p2 = get_llm_provider(settings=_settings("mock"))
    assert p1 is p2


# ---------------------------------------------------------------------------
# close_llm_provider — shutdown lifecycle


@pytest.mark.asyncio
async def test_close_noop_when_singleton_not_set() -> None:
    """No-op safe even если init не вызывался."""
    await close_llm_provider()
    assert factory_module._llm_provider_instance is None


@pytest.mark.asyncio
async def test_close_resets_singleton_to_none() -> None:
    """После close() singleton снова None — next init заново built'ит."""
    init_llm_provider(_settings("mock"))
    assert factory_module._llm_provider_instance is not None
    await close_llm_provider()
    assert factory_module._llm_provider_instance is None


@pytest.mark.asyncio
async def test_close_calls_aclose_on_provider() -> None:
    """`LLMProvider.aclose` всегда defined в ABC (#350 follow-up); close
    вызывает его — real providers override'ят с aclose pool'а."""
    fake = MockProvider()
    aclose_mock = AsyncMock()
    fake.aclose = aclose_mock  # type: ignore[method-assign]
    factory_module._llm_provider_instance = fake
    await close_llm_provider()
    aclose_mock.assert_awaited_once()
    assert factory_module._llm_provider_instance is None


@pytest.mark.asyncio
async def test_close_uses_base_noop_for_stateless_provider() -> None:
    """MockProvider не override'ит aclose — base noop вызывается без
    падения. Singleton resets."""
    init_llm_provider(_settings("mock"))
    await close_llm_provider()
    assert factory_module._llm_provider_instance is None
