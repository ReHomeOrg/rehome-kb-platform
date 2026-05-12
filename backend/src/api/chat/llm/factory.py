"""FastAPI Depends factory для LLMProvider — env-based selection.

`Settings.llm_provider` (env `LLM_PROVIDER`, default 'mock'):
- `mock` → `MockProvider` (тесты, dev).
- `vllm` → NotImplementedError (E3.7 backlog).
- любое другое → ValueError.
"""

from fastapi import Depends

from src.api.chat.llm.base import LLMProvider
from src.api.chat.llm.mock import MockProvider
from src.api.chat.llm.vllm import VLLMProvider
from src.api.config import Settings, get_settings


def get_llm_provider(
    settings: Settings = Depends(get_settings),
) -> LLMProvider:
    """Возвращает LLMProvider instance согласно settings.llm_provider.

    MockProvider stateless и cheap — создаётся на каждый запрос.
    VLLMProvider держит httpx.AsyncClient instance attribute; пока
    тоже создаётся per-request. Для production latency — backlog:
    lru_cache / singleton client через Lifespan (см. vllm.py docstring).
    """
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return MockProvider()
    if provider == "vllm":
        return VLLMProvider(
            url=settings.llm_vllm_url,
            model=settings.llm_vllm_model,
            timeout_seconds=settings.llm_vllm_timeout_seconds,
            api_key=settings.llm_vllm_api_key,
        )
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
