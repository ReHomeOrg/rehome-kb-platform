"""Unit-тесты GigaChatProvider (RU LLM, Сбер).

Использует `httpx.MockTransport` для OAuth + chat completions. Покрывает:
- OAuth: token fetched на первый call, cached на повторный (no refresh).
- OAuth: token refresh при expiry.
- complete: OpenAI-shaped response → LLMResponse.
- complete: missing usage → len//4 fallback.
- stream: yields chunks, skip [DONE], skip malformed.
- Factory: gigachat → GigaChatProvider с правильным config; missing
  credentials → ValueError.
- Constructor: пустые credentials → ValueError.
"""

import json
from collections.abc import Callable

import httpx
import pytest

from src.api.chat.llm import LLMMessage
from src.api.chat.llm.factory import get_llm_provider
from src.api.chat.llm.gigachat import GigaChatProvider
from src.api.config import Settings

# httpx.MockTransport handler signature.
_Handler = Callable[[httpx.Request], httpx.Response]


def _oauth_response(token: str = "tk-1", expires_at_ms: int | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"access_token": token}
    if expires_at_ms is not None:
        payload["expires_at"] = expires_at_ms
    else:
        # Default: 30 minutes from now (Sber default TTL).
        import time as _time

        payload["expires_at"] = int((_time.time() + 30 * 60) * 1000)
    return payload


def _completion_response(content: str = "Привет", tokens: int | None = 5) -> dict[str, object]:
    payload: dict[str, object] = {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    if tokens is not None:
        payload["usage"] = {"completion_tokens": tokens}
    return payload


def _stream_body(chunks: list[str]) -> bytes:
    lines: list[str] = []
    for chunk in chunks:
        lines.append(
            f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}]}, ensure_ascii=False)}"
        )
        lines.append("")
    lines.append("data: [DONE]")
    lines.append("")
    return ("\n".join(lines)).encode("utf-8")


def _make_provider_with_transports(
    *,
    oauth_handler: _Handler,
    api_handler: _Handler,
) -> GigaChatProvider:
    provider = GigaChatProvider(
        client_id="cid",
        client_secret="csecret",
        oauth_url="https://oauth.example/token",
        base_url="https://api.example",
        model="GigaChat",
        scope="GIGACHAT_API_PERS",
        timeout_seconds=5,
    )
    provider._oauth_client = httpx.AsyncClient(
        transport=httpx.MockTransport(oauth_handler),
    )
    provider._api_client = httpx.AsyncClient(
        transport=httpx.MockTransport(api_handler),
        base_url="https://api.example",
    )
    return provider


# ---------------------------------------------------------------------------
# Constructor + factory


def test_constructor_rejects_empty_credentials() -> None:
    with pytest.raises(ValueError, match="client_id"):
        GigaChatProvider(
            client_id="",
            client_secret="x",
            oauth_url="https://o",
            base_url="https://a",
            model="GigaChat",
        )


def test_factory_gigachat_requires_credentials() -> None:
    settings = Settings(LLM_PROVIDER="gigachat")
    with pytest.raises(ValueError, match="CLIENT_ID"):
        get_llm_provider(settings)


def test_factory_gigachat_builds_provider() -> None:
    settings = Settings(
        LLM_PROVIDER="gigachat",
        LLM_GIGACHAT_CLIENT_ID="cid",
        LLM_GIGACHAT_CLIENT_SECRET="csecret",
    )
    provider = get_llm_provider(settings)
    assert isinstance(provider, GigaChatProvider)


def test_factory_unknown_provider_raises() -> None:
    settings = Settings(LLM_PROVIDER="nope")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_llm_provider(settings)


# ---------------------------------------------------------------------------
# OAuth + token caching


@pytest.mark.asyncio
async def test_oauth_token_cached_after_first_fetch() -> None:
    call_count = {"n": 0}

    def oauth_handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        # Verify Basic auth + RqUID + scope body.
        assert request.headers["Authorization"].startswith("Basic ")
        assert "RqUID" in request.headers
        assert b"scope=GIGACHAT_API_PERS" in request.content
        return httpx.Response(200, json=_oauth_response("tk-1"))

    def api_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_response())

    provider = _make_provider_with_transports(oauth_handler=oauth_handler, api_handler=api_handler)
    try:
        # Two calls → only one OAuth fetch.
        await provider.complete([LLMMessage(role="user", content="q")], "sys")
        await provider.complete([LLMMessage(role="user", content="q")], "sys")
        assert call_count["n"] == 1
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_oauth_token_refreshed_when_expired() -> None:
    call_count = {"n": 0}

    def oauth_handler(_request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        # Return token expired in the past — force refresh next call.
        return httpx.Response(
            200,
            json=_oauth_response(f"tk-{call_count['n']}", expires_at_ms=0),
        )

    def api_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_response())

    provider = _make_provider_with_transports(oauth_handler=oauth_handler, api_handler=api_handler)
    try:
        await provider.complete([LLMMessage(role="user", content="q")], "sys")
        await provider.complete([LLMMessage(role="user", content="q")], "sys")
        assert call_count["n"] == 2
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_oauth_missing_token_raises() -> None:
    def oauth_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})  # no access_token

    def api_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_response())

    provider = _make_provider_with_transports(oauth_handler=oauth_handler, api_handler=api_handler)
    try:
        with pytest.raises(RuntimeError, match="access_token"):
            await provider.complete([LLMMessage(role="user", content="q")], "sys")
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_oauth_expires_in_fallback() -> None:
    """Если `expires_at` отсутствует, используем `expires_in` (RFC 6749)."""

    def oauth_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "tk-1", "expires_in": 1800},
        )

    def api_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion_response())

    provider = _make_provider_with_transports(oauth_handler=oauth_handler, api_handler=api_handler)
    try:
        result = await provider.complete([LLMMessage(role="user", content="q")], "sys")
        assert result.content == "Привет"
    finally:
        await provider.aclose()


# ---------------------------------------------------------------------------
# complete


@pytest.mark.asyncio
async def test_complete_returns_parsed_llm_response() -> None:
    def oauth_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_oauth_response("tk-1"))

    api_calls = []

    def api_handler(request: httpx.Request) -> httpx.Response:
        api_calls.append(request)
        # Verify Authorization + payload shape.
        assert request.headers["Authorization"] == "Bearer tk-1"
        body = json.loads(request.content)
        assert body["model"] == "GigaChat"
        assert body["stream"] is False
        assert body["messages"][0] == {"role": "system", "content": "sys"}
        assert body["messages"][1] == {"role": "user", "content": "q"}
        return httpx.Response(200, json=_completion_response("Hi there", 3))

    provider = _make_provider_with_transports(oauth_handler=oauth_handler, api_handler=api_handler)
    try:
        result = await provider.complete([LLMMessage(role="user", content="q")], "sys")
        assert result.content == "Hi there"
        assert result.token_count == 3
        assert result.duration_ms >= 0
        assert len(api_calls) == 1
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_missing_usage_falls_back_to_chars_div_4() -> None:
    def oauth_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_oauth_response())

    def api_handler(_request: httpx.Request) -> httpx.Response:
        # 16-char content, no usage → 16/4 = 4.
        return httpx.Response(200, json=_completion_response("1234567890123456", tokens=None))

    provider = _make_provider_with_transports(oauth_handler=oauth_handler, api_handler=api_handler)
    try:
        result = await provider.complete([LLMMessage(role="user", content="q")], "sys")
        assert result.token_count == 4
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_propagates_5xx_error() -> None:
    def oauth_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_oauth_response())

    def api_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    provider = _make_provider_with_transports(oauth_handler=oauth_handler, api_handler=api_handler)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await provider.complete([LLMMessage(role="user", content="q")], "sys")
    finally:
        await provider.aclose()


# ---------------------------------------------------------------------------
# stream


@pytest.mark.asyncio
async def test_stream_yields_chunks() -> None:
    def oauth_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_oauth_response())

    def api_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_stream_body(["Hello", " ", "world"]))

    provider = _make_provider_with_transports(oauth_handler=oauth_handler, api_handler=api_handler)
    try:
        chunks: list[str] = []
        async for c in provider.stream([LLMMessage(role="user", content="q")], "sys"):
            chunks.append(c)
        assert "".join(chunks) == "Hello world"
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_stream_skips_malformed_json() -> None:
    def oauth_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_oauth_response())

    body = (
        b"data: {not json}\n\n"
        b"data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]}).encode() + b"\n\n"
        b"data: [DONE]\n\n"
    )

    def api_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    provider = _make_provider_with_transports(oauth_handler=oauth_handler, api_handler=api_handler)
    try:
        chunks: list[str] = []
        async for c in provider.stream([LLMMessage(role="user", content="q")], "sys"):
            chunks.append(c)
        # Malformed line skipped; "ok" yielded.
        assert chunks == ["ok"]
    finally:
        await provider.aclose()
