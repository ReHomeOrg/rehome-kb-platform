"""Unit-тесты get_llm_provider factory (E3.3 #65).

Покрывает:
- llm_provider='mock' → MockProvider instance.
- llm_provider='vllm' → NotImplementedError (E3.7 backlog).
- Unknown provider → ValueError.
- Case-insensitive: 'MOCK', 'Mock' тоже работают.
"""

import pytest

from src.api.chat.llm import MockProvider, get_llm_provider
from src.api.config import Settings


def _settings(provider: str) -> Settings:
    return Settings(LLM_PROVIDER=provider)


def test_factory_returns_mock_for_mock_setting() -> None:
    provider = get_llm_provider(settings=_settings("mock"))
    assert isinstance(provider, MockProvider)


def test_factory_case_insensitive() -> None:
    provider = get_llm_provider(settings=_settings("MOCK"))
    assert isinstance(provider, MockProvider)


# NB: было `vllm_raises_not_implemented` до E3.7. Теперь vllm работает —
# тесты VLLMProvider в test_llm_vllm.py покрывают factory dispatch.


def test_factory_unknown_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_llm_provider(settings=_settings("openai"))
