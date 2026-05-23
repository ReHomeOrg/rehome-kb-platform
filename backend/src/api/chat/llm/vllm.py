"""VLLMProvider — production-ready LLM adapter (E3.7 #73).

vLLM — self-hosted inference server с OpenAI-compatible API. Этот
adapter использует `httpx.AsyncClient` для вызовов
`POST /v1/chat/completions`.

Native streaming: при `stream=true` vLLM возвращает SSE-stream с
`data: <json>\\n\\n` events, оканчивающимися `data: [DONE]`.

ADR-0001 — self-hosted LLM. ФЗ-152 — internal network only.

**Singleton client** (#350): factory.py держит module-level instance,
initialized в FastAPI lifespan; `aclose()` вызывается на shutdown.
Connection pool reuse через requests одной сессии.
"""

import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from src.api.chat.llm.base import LLMMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Совпадает с router._CHARS_PER_TOKEN — fallback heuristic если vLLM
# не вернул usage.completion_tokens. Дублируется здесь, чтобы избежать
# circular import (router → llm vs llm → router); правило трёх не
# сработало (2 копии), но если появится 3-я — вынести в base.py.
_CHARS_PER_TOKEN_FALLBACK = 4

# SSE terminator (OpenAI spec) — vLLM шлёт после последнего chunk'а.
_SSE_DONE_MARKER = "[DONE]"
_SSE_DATA_PREFIX = "data: "


class VLLMProvider(LLMProvider):
    """LLMProvider, вызывающий vLLM по OpenAI-compatible HTTP API.

    `complete()` — single request, parsing `choices[0].message.content`
    и `usage.completion_tokens` из response.

    `stream()` — `stream=true`, парсинг SSE chunks. Yields content deltas.

    Network errors (httpx.HTTPError, TimeoutException) — re-raise:
    router/SSE handler ловит и возвращает 5xx / `event: error`.
    """

    def __init__(
        self,
        *,
        url: str,
        model: str,
        timeout_seconds: int = 60,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        headers = {"Content-Type": "application/json"}
        if api_key is not None:
            # NB: api_key НЕ должен попадать в логи — httpx default
            # не логирует headers; logger.exception ниже также не
            # включает request.headers.
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=url,
            timeout=timeout_seconds,
            headers=headers,
        )

    def _build_messages(
        self, messages: list[LLMMessage], system_prompt: str
    ) -> list[dict[str, str]]:
        """Prepend system_prompt + map LLMMessage → OpenAI dict format."""
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
        """POST /v1/chat/completions с stream=false."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._build_messages(messages, system_prompt),
            "max_tokens": max_tokens,
            "stream": False,
        }
        start = time.perf_counter()
        response = await self._client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        duration_ms = int((time.perf_counter() - start) * 1000)

        # Defensive extraction: vLLM follows OpenAI spec, но parse без
        # KeyError fallthrough на необычные responses.
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
        """POST /v1/chat/completions с stream=true; yields content deltas.

        SSE формат (per OpenAI spec):
        ```
        data: {"choices":[{"delta":{"content":"chunk"},...}]}
        data: [DONE]
        ```

        Malformed JSON-строки skip'ятся с DEBUG-логом (без эха content'а)
        — defensive против upstream bugs.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._build_messages(messages, system_prompt),
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with self._client.stream("POST", "/v1/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith(_SSE_DATA_PREFIX):
                    # Empty line (chunk separator), event: line, etc. — skip.
                    continue
                body = line[len(_SSE_DATA_PREFIX) :].strip()
                if body == _SSE_DONE_MARKER:
                    return
                try:
                    chunk = json.loads(body)
                except json.JSONDecodeError:
                    # Defensive: vLLM не должен присылать malformed JSON,
                    # но если случится — не падаем mid-stream. Без эха
                    # content'а в логе (privacy).
                    logger.debug("vllm.malformed_sse_chunk_skipped")
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content_chunk = delta.get("content")
                if content_chunk:
                    yield content_chunk

    async def aclose(self) -> None:
        """Close httpx client (для test cleanup; production — Lifespan)."""
        await self._client.aclose()
