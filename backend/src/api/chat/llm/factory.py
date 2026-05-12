"""FastAPI Depends factory для LLMProvider — env-based selection.

`Settings.llm_provider` (env `LLM_PROVIDER`, default 'mock'):
- `mock` → `MockProvider` (тесты, dev).
- `vllm` → NotImplementedError (E3.7 backlog).
- любое другое → ValueError.
"""

from fastapi import Depends

from src.api.chat.llm.base import LLMProvider
from src.api.chat.llm.mock import MockProvider
from src.api.config import Settings, get_settings

_VLLM_NOT_IMPLEMENTED = (
    "vLLM adapter будет реализован в E3.7. Сейчас используйте " "LLM_PROVIDER=mock для dev/test."
)


def get_llm_provider(
    settings: Settings = Depends(get_settings),
) -> LLMProvider:
    """Возвращает LLMProvider instance согласно settings.llm_provider.

    Provider instances stateless и cheap — создаются на каждый запрос
    (не singleton). Future vLLM adapter может потребовать httpx client
    с connection pool — тогда введём lru_cache или DI singleton.
    """
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return MockProvider()
    if provider == "vllm":
        raise NotImplementedError(_VLLM_NOT_IMPLEMENTED)
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
