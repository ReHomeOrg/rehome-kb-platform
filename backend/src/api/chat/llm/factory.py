"""FastAPI Depends factory для LLMProvider — env-based selection.

`Settings.llm_provider` (env `LLM_PROVIDER`, default 'mock'):
- `mock` → `MockProvider` (тесты, dev).
- `vllm` → `VLLMProvider` (self-hosted OpenAI-compatible).
- `gigachat` → `GigaChatProvider` (Sber RU sovereign).
- `yandex_gpt` → `YandexGptProvider` (Yandex Cloud RU sovereign).
- любое другое → ValueError.

Singleton lifecycle (#350): real providers (vllm / gigachat / yandex_gpt)
держат `httpx.AsyncClient` connection pool. Per-request construction
повторно открывал TCP/TLS handshake — production latency hit. Теперь
`init_llm_provider` вызывается из FastAPI lifespan на startup; instance
stored в module-level _llm_provider_instance; `get_llm_provider`
returns shared reference. На shutdown `close_llm_provider` вызывает
`aclose()` на httpx client'е.

Tests с `app.dependency_overrides[get_llm_provider]` обходят singleton
полностью — никакого test isolation issue.
"""

from fastapi import Depends

from src.api.chat.llm.base import LLMProvider
from src.api.chat.llm.gigachat import GigaChatProvider
from src.api.chat.llm.mock import MockProvider
from src.api.chat.llm.vllm import VLLMProvider
from src.api.chat.llm.yandex_gpt import YandexGptProvider
from src.api.config import Settings, get_settings

# Module-level singleton — initialized по `init_llm_provider`, accessed
# через `get_llm_provider`. None до первой инициализации.
_llm_provider_instance: LLMProvider | None = None


def build_llm_provider(settings: Settings) -> LLMProvider:
    """Pure constructor — выбирает class по settings + builds instance.

    Raise `ValueError` если provider unknown или required env vars missing.

    Public для тестов (dispatch coverage без singleton state). Production
    code должен использовать `init_llm_provider` / `get_llm_provider`.
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
    if provider == "yandex_gpt":
        if not settings.llm_yandex_api_key or not settings.llm_yandex_folder_id:
            raise ValueError(
                "LLM_PROVIDER=yandex_gpt requires LLM_YANDEX_API_KEY "
                "and LLM_YANDEX_FOLDER_ID to be set"
            )
        return YandexGptProvider(
            api_key=settings.llm_yandex_api_key,
            folder_id=settings.llm_yandex_folder_id,
            base_url=settings.llm_yandex_base_url,
            model=settings.llm_yandex_model,
            model_version=settings.llm_yandex_model_version,
            timeout_seconds=settings.llm_yandex_timeout_seconds,
        )
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")


def init_llm_provider(settings: Settings) -> LLMProvider:
    """Initialize module-level singleton. Idempotent (повторный вызов
    возвращает existing instance без re-build'а).

    Called из FastAPI lifespan на startup.
    """
    global _llm_provider_instance
    if _llm_provider_instance is None:
        _llm_provider_instance = build_llm_provider(settings)
    return _llm_provider_instance


async def close_llm_provider() -> None:
    """Closes underlying httpx client pool. Called from lifespan shutdown.

    No-op если singleton не был initialized или provider не имеет `aclose`
    (e.g. MockProvider).
    """
    global _llm_provider_instance
    if _llm_provider_instance is None:
        return
    aclose = getattr(_llm_provider_instance, "aclose", None)
    if aclose is not None:
        await aclose()
    _llm_provider_instance = None


def get_llm_provider(
    settings: Settings = Depends(get_settings),
) -> LLMProvider:
    """Возвращает shared LLMProvider singleton.

    Если `init_llm_provider` ещё не вызвался (early bootstrap, tests без
    lifespan), lazy-init'ит. Тесты с `app.dependency_overrides
    [get_llm_provider]` bypass'ят singleton полностью.
    """
    if _llm_provider_instance is None:
        return init_llm_provider(settings)
    return _llm_provider_instance


__all__ = [
    "build_llm_provider",
    "close_llm_provider",
    "get_llm_provider",
    "init_llm_provider",
]
