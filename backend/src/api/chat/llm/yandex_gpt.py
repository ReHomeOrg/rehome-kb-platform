"""YandexGPT LLM adapter (Yandex Cloud, RU sovereign).

Использует OpenAI-compatible endpoint:
- POST `/v1/chat/completions`
- Auth: `Authorization: Api-Key <key>` (service account API key).
- `model` параметр resolves в `gpt://<folder_id>/<model>/<version>`
  per Yandex Cloud Foundation Models API.

Проще чем GigaChat (нет OAuth flow / token caching) — Api-Key долгоживущий.
Production — store key через Yandex Lockbox + env injection.

ТЗ §1.2 / ФЗ-152 — данные не покидают РФ-инфраструктуру Yandex Cloud.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from src.api.chat.llm.base import LLMMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN_FALLBACK = 4

_SSE_DONE_MARKER = "[DONE]"
_SSE_DATA_PREFIX = "data: "


class YandexGptProvider(LLMProvider):
    """LLMProvider, вызывающий YandexGPT через OpenAI-compatible API.

    `model_uri` параметр resolves в `gpt://<folder_id>/<model>/<version>`
    при инициализации — единый string передаётся в POST payload's `model`
    field.

    `complete()` — single request, parsing OpenAI-shaped response.
    `stream()` — SSE streaming чанков.

    Network / API errors — re-raise: router/SSE handler handle'ит.
    """

    def __init__(
        self,
        *,
        api_key: str,
        folder_id: str,
        base_url: str,
        model: str,
        model_version: str = "latest",
        timeout_seconds: int = 60,
    ) -> None:
        if not api_key or not folder_id:
            raise ValueError(
                "YandexGptProvider requires api_key and folder_id "
                "(LLM_YANDEX_API_KEY / LLM_YANDEX_FOLDER_ID)"
            )
        # Yandex Cloud model URI convention.
        self._model_uri = f"gpt://{folder_id}/{model}/{model_version}"
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Api-Key {api_key}",
                "Content-Type": "application/json",
            },
        )

    def _build_messages(
        self, messages: list[LLMMessage], system_prompt: str
    ) -> list[dict[str, str]]:
        """OpenAI-shaped messages с system_prompt prepended."""
        result: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        for m in messages:
            result.append({"role": m.role, "content": m.content})
        return result

    async def complete(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._model_uri,
            "messages": self._build_messages(messages, system_prompt),
            "max_tokens": max_tokens,
            "stream": False,
        }
        start = time.perf_counter()
        response = await self._client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        duration_ms = int((time.perf_counter() - start) * 1000)

        choices = data.get("choices") or []
        content = ""
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content") or ""

        usage = data.get("usage") or {}
        token_count = usage.get("completion_tokens")
        if not isinstance(token_count, int):
            token_count = len(content) // _CHARS_PER_TOKEN_FALLBACK

        return LLMResponse(
            content=content,
            token_count=token_count,
            duration_ms=duration_ms,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """SSE streaming OpenAI-compatible (`data: ...\\n\\n` + `[DONE]`)."""
        payload: dict[str, Any] = {
            "model": self._model_uri,
            "messages": self._build_messages(messages, system_prompt),
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with self._client.stream("POST", "/v1/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith(_SSE_DATA_PREFIX):
                    continue
                body = line[len(_SSE_DATA_PREFIX) :].strip()
                if body == _SSE_DONE_MARKER:
                    return
                try:
                    chunk = json.loads(body)
                except json.JSONDecodeError:
                    logger.debug("yandex_gpt.malformed_sse_chunk_skipped")
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content_chunk = delta.get("content")
                if content_chunk:
                    yield content_chunk

    async def aclose(self) -> None:
        """Close httpx client."""
        await self._client.aclose()
