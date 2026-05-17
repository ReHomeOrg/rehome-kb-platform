"""FastAPI Depends factory для LLMProvider — env-based selection.

`Settings.llm_provider` (env `LLM_PROVIDER`, default 'mock'):
- `mock` → `MockProvider` (тесты, dev).
- `vllm` → `VLLMProvider` (self-hosted OpenAI-compatible).
- `gigachat` → `GigaChatProvider` (Sber RU sovereign LLM).
- любое другое → ValueError.
"""

from fastapi import Depends

from src.api.chat.llm.base import LLMProvider
from src.api.chat.llm.gigachat import GigaChatProvider
from src.api.chat.llm.mock import MockProvider
from src.api.chat.llm.vllm import VLLMProvider
from src.api.config import Settings, get_settings


def get_llm_provider(
    settings: Settings = Depends(get_settings),
) -> LLMProvider:
    """Возвращает LLMProvider instance согласно settings.llm_provider.

    MockProvider stateless и cheap — создаётся на каждый запрос.
    VLLMProvider / GigaChatProvider держат httpx.AsyncClient instance
    attribute; пока тоже создаются per-request. Для production latency —
    backlog: lru_cache / singleton client через Lifespan.
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
    if provider == "gigachat":
        if not settings.llm_gigachat_client_id or not settings.llm_gigachat_client_secret:
            raise ValueError(
                "LLM_PROVIDER=gigachat requires LLM_GIGACHAT_CLIENT_ID "
                "and LLM_GIGACHAT_CLIENT_SECRET to be set"
            )
        return GigaChatProvider(
            client_id=settings.llm_gigachat_client_id,
            client_secret=settings.llm_gigachat_client_secret,
            oauth_url=settings.llm_gigachat_oauth_url,
            base_url=settings.llm_gigachat_base_url,
            model=settings.llm_gigachat_model,
            scope=settings.llm_gigachat_scope,
            timeout_seconds=settings.llm_gigachat_timeout_seconds,
            verify_ssl=settings.llm_gigachat_verify_ssl,
        )
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
