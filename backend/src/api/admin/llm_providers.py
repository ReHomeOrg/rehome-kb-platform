"""LLM provider catalog для GET /admin/llm/providers (#228).

Static enumeration 4 known providers (mock, vllm, gigachat, yandex_gpt).
Build'ится из текущего `Settings` — `id` fixed строки, `model` field
динамически берётся из соответствующего env-config (model bump → response
обновляется без deploy schema'а).

`is_current` = (settings.llm_provider == provider.id).

Status:
- 'mock' / 'vllm' — EXPERIMENTAL (mock — для тестов; vllm — self-host
  PoC).
- 'gigachat' / 'yandex_gpt' — ACTIVE (RU sovereign, production-grade
  per #257/#258).

Context lengths / streaming capability — hardcoded from vendor docs:
- GigaChat: 32K context (per Sber docs), supports streaming.
- YandexGPT: 8K context, supports streaming.
- vLLM: depends on model (Qwen2.5-7B-Instruct = 32K), streaming yes.
- Mock: N/A (тестовый stub).

Cost rates / health checks — null (источников нет, см. schemas docstring).
"""

from __future__ import annotations

from src.api.admin.schemas import LlmProviderView
from src.api.config import Settings


def build_provider_catalog(settings: Settings) -> list[LlmProviderView]:
    """Возвращает список 4 known providers с `is_current` flag.

    Detection строится строго по `settings.llm_provider` (lowercased).
    Unknown / missing — все 4 имеют `is_current=False` (admin UI понимает
    «no active provider»).
    """
    current = settings.llm_provider.lower()
    return [
        LlmProviderView(
            id="mock",
            name="MockProvider (deterministic stub)",
            vendor="rehome-internal",
            model=None,
            status="EXPERIMENTAL",
            is_current=(current == "mock"),
            max_context_tokens=None,
            supports_streaming=True,
        ),
        LlmProviderView(
            id="vllm",
            name="vLLM (self-hosted, OpenAI-compat)",
            vendor="rehome-internal",
            model=settings.llm_vllm_model,
            status="EXPERIMENTAL",
            is_current=(current == "vllm"),
            # Qwen2.5-7B-Instruct context — 32K (model-default; admin может
            # переопределить через env, но мы не tracking'ем).
            max_context_tokens=32768,
            supports_streaming=True,
        ),
        LlmProviderView(
            id="gigachat",
            name="GigaChat (Sber, RU sovereign)",
            vendor="sber",
            model=settings.llm_gigachat_model,
            status="ACTIVE",
            is_current=(current == "gigachat"),
            # Per Sber docs (GigaChat-Pro): 32K context.
            max_context_tokens=32768,
            supports_streaming=True,
        ),
        LlmProviderView(
            id="yandex_gpt",
            name="YandexGPT (Yandex Cloud, RU sovereign)",
            vendor="yandex",
            model=f"{settings.llm_yandex_model}/{settings.llm_yandex_model_version}",
            status="ACTIVE",
            is_current=(current == "yandex_gpt"),
            # YandexGPT-Lite — 8K input context (per Yandex Cloud docs).
            max_context_tokens=8192,
            supports_streaming=True,
        ),
    ]


__all__ = ["build_provider_catalog"]
