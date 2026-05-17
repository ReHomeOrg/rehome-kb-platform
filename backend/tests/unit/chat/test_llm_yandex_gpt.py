"""Unit tests для YandexGptProvider (Yandex Cloud, RU LLM).

Использует `httpx.MockTransport`. Покрывает:
- Constructor валидация (api_key + folder_id required).
- Factory: yandex_gpt → YandexGptProvider; missing creds → ValueError.
- complete: payload shape (model_uri resolution `gpt://folder_id/model/ver`,
  Authorization header).
- complete: usage parsing + fallback len//4.
- complete: 5xx propagates.
- stream: yields chunks, skip [DONE], skip malformed JSON.
"""

import json
from collections.abc import Callable

import httpx
import pytest

from src.api.chat.llm import LLMMessage, YandexGptProvider
from src.api.chat.llm.factory import get_llm_provider
from src.api.config import Settings

_Handler = Callable[[httpx.Request], httpx.Response]


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


def _make_provider(*, handler: _Handler, model_version: str = "latest") -> YandexGptProvider:
    provider = YandexGptProvider(
        api_key="api-key-test",
        folder_id="b1g123",
        base_url="https://api.example",
        model="yandexgpt-lite",
        model_version=model_version,
        timeout_seconds=5,
    )
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.example",
        headers={
            "Authorization": "Api-Key api-key-test",
            "Content-Type": "application/json",
        },
    )
    return provider


# ---------------------------------------------------------------------------
# Constructor + factory


def test_constructor_rejects_empty_api_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        YandexGptProvider(
            api_key="",
            folder_id="b1g",
            base_url="https://x",
            model="yandexgpt-lite",
        )


def test_constructor_rejects_empty_folder_id() -> None:
    with pytest.raises(ValueError, match="folder_id"):
        YandexGptProvider(
            api_key="key",
            folder_id="",
            base_url="https://x",
            model="yandexgpt-lite",
        )


def test_factory_yandex_gpt_requires_credentials() -> None:
    settings = Settings(LLM_PROVIDER="yandex_gpt")
    with pytest.raises(ValueError, match="API_KEY"):
        get_llm_provider(settings)


def test_factory_yandex_gpt_builds_provider() -> None:
    settings = Settings(
        LLM_PROVIDER="yandex_gpt",
        LLM_YANDEX_API_KEY="key",
        LLM_YANDEX_FOLDER_ID="b1g",
    )
    provider = get_llm_provider(settings)
    assert isinstance(provider, YandexGptProvider)


# ---------------------------------------------------------------------------
# complete


@pytest.mark.asyncio
async def test_complete_payload_includes_model_uri_and_auth() -> None:
    api_calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        api_calls.append(request)
        assert request.headers["Authorization"] == "Api-Key api-key-test"
        body = json.loads(request.content)
        # model_uri должен быть gpt://folder_id/model/version
        assert body["model"] == "gpt://b1g123/yandexgpt-lite/latest"
        assert body["stream"] is False
        assert body["messages"][0] == {"role": "system", "content": "sys"}
        return httpx.Response(200, json=_completion_response("Hi", 3))

    provider = _make_provider(handler=handler)
    try:
        result = await provider.complete([LLMMessage(role="user", content="q")], "sys")
        assert result.content == "Hi"
        assert result.token_count == 3
        assert result.duration_ms >= 0
        assert len(api_calls) == 1
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_uses_pinned_model_version() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gpt://b1g123/yandexgpt-lite/rc"
        return httpx.Response(200, json=_completion_response())

    provider = _make_provider(handler=handler, model_version="rc")
    try:
        await provider.complete([LLMMessage(role="user", content="q")], "sys")
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_missing_usage_fallbacks_to_chars_div_4() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        # 16-char content, no usage → 4 tokens.
        return httpx.Response(200, json=_completion_response("1234567890123456", tokens=None))

    provider = _make_provider(handler=handler)
    try:
        result = await provider.complete([LLMMessage(role="user", content="q")], "sys")
        assert result.token_count == 4
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_propagates_5xx_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    provider = _make_provider(handler=handler)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await provider.complete([LLMMessage(role="user", content="q")], "sys")
    finally:
        await provider.aclose()


# ---------------------------------------------------------------------------
# stream


@pytest.mark.asyncio
async def test_stream_yields_chunks() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_stream_body(["Hello", " ", "world"]))

    provider = _make_provider(handler=handler)
    try:
        chunks: list[str] = []
        async for c in provider.stream([LLMMessage(role="user", content="q")], "sys"):
            chunks.append(c)
        assert "".join(chunks) == "Hello world"
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_stream_skips_malformed_json() -> None:
    body = (
        b"data: {malformed}\n\n"
        b"data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]}).encode() + b"\n\n"
        b"data: [DONE]\n\n"
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    provider = _make_provider(handler=handler)
    try:
        chunks: list[str] = []
        async for c in provider.stream([LLMMessage(role="user", content="q")], "sys"):
            chunks.append(c)
        assert chunks == ["ok"]
    finally:
        await provider.aclose()
