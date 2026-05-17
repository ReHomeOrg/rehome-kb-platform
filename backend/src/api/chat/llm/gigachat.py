"""GigaChat LLM adapter (Sber, RU sovereign).

Auth flow:
1. POST /api/v2/oauth с Basic auth (client_id:client_secret base64) +
   header `RqUID` + body `scope=GIGACHAT_API_PERS` → JSON `access_token` +
   `expires_at` (Unix ms).
2. Authorization: Bearer <access_token> на POST /api/v1/chat/completions.

Token caching: in-memory с refresh за 60sec до expiry (clock skew safety).
Per-provider state — provider instance держит cache; разные Depends-instances
дублируют OAuth calls (acceptable trade-off для now; backlog: singleton
client через Lifespan).

ТЗ §1.2 / ФЗ-152 — данные не покидают РФ-инфраструктуру Сбера. Все
sensitive (prompt, completion) — внутри Russian boundary.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from base64 import b64encode
from collections.abc import AsyncIterator
from typing import Any

import httpx

from src.api.chat.llm.base import LLMMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN_FALLBACK = 4

# OAuth token refresh заранее за это окно от настоящего expiry — защита
# от clock skew и race на конце окна.
_TOKEN_REFRESH_LEAD_SECONDS = 60

# SSE markers (OpenAI-compatible streaming, GigaChat следует тому же).
_SSE_DONE_MARKER = "[DONE]"
_SSE_DATA_PREFIX = "data: "


class GigaChatProvider(LLMProvider):
    """LLMProvider, вызывающий GigaChat по OAuth + chat completions API.

    `complete()` — single request, parsing OpenAI-shaped response.
    `stream()` — SSE streaming чанков.

    OAuth caches access_token + expiry — refresh за 60sec до конца. Token
    state защищён `asyncio.Lock` от race condition при concurrent calls.

    Network / OAuth / API errors — re-raise: router/SSE handler ловят
    и возвращают 5xx / `event: error`.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        oauth_url: str,
        base_url: str,
        model: str,
        scope: str = "GIGACHAT_API_PERS",
        timeout_seconds: int = 60,
        verify_ssl: bool = True,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError(
                "GigaChatProvider requires client_id and client_secret "
                "(LLM_GIGACHAT_CLIENT_ID / LLM_GIGACHAT_CLIENT_SECRET)"
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._oauth_url = oauth_url
        self._model = model
        self._scope = scope
        # Two clients — один для OAuth (отдельный host), другой для API.
        # Verify flag общий: production должен быть True, dev/test может
        # обнулить через env.
        self._oauth_client = httpx.AsyncClient(
            timeout=timeout_seconds,
            verify=verify_ssl,
        )
        self._api_client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            verify=verify_ssl,
        )
        # Token cache: (token, expires_at_unix_seconds). Защищено lock'ом.
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    async def _get_access_token(self) -> str:
        """Returns valid access_token, refreshing если needed.

        Lock protects от concurrent refresh — первый caller обновляет,
        остальные ждут на lock и reuse кэш.
        """
        async with self._token_lock:
            now = time.time()
            if self._token is not None and now < self._token_expires_at:
                return self._token
            # Refresh
            basic = b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode("ascii")
            headers = {
                "Authorization": f"Basic {basic}",
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }
            response = await self._oauth_client.post(
                self._oauth_url,
                headers=headers,
                content=f"scope={self._scope}",
            )
            response.raise_for_status()
            data = response.json()
            token = data.get("access_token")
            # `expires_at` — Unix milliseconds; защитимся от alternate
            # `expires_in` (seconds, OAuth2 RFC fallback).
            if "expires_at" in data:
                expires_at_seconds = float(data["expires_at"]) / 1000.0
            elif "expires_in" in data:
                expires_at_seconds = now + float(data["expires_in"])
            else:
                # Defensive: если ни одного — кэш на 25 минут (стандартный
                # GigaChat TTL — 30 минут).
                expires_at_seconds = now + 25 * 60
            if not isinstance(token, str) or not token:
                raise RuntimeError("GigaChat OAuth: missing access_token")
            self._token = token
            self._token_expires_at = expires_at_seconds - _TOKEN_REFRESH_LEAD_SECONDS
            return token

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
        token = await self._get_access_token()
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._build_messages(messages, system_prompt),
            "max_tokens": max_tokens,
            "stream": False,
        }
        start = time.perf_counter()
        response = await self._api_client.post(
            "/api/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
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
        """SSE streaming. GigaChat следует OpenAI стандарту
        (`data: <json>\\n\\n` events, terminator `[DONE]`).
        """
        token = await self._get_access_token()
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": self._build_messages(messages, system_prompt),
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with self._api_client.stream(
            "POST",
            "/api/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
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
                    logger.debug("gigachat.malformed_sse_chunk_skipped")
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content_chunk = delta.get("content")
                if content_chunk:
                    yield content_chunk

    async def aclose(self) -> None:
        """Close httpx clients (для test cleanup; production — Lifespan)."""
        await self._oauth_client.aclose()
        await self._api_client.aclose()
