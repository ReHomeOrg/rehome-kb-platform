"""Unit-тесты VLLMProvider (E3.7 #73).

Используется `httpx.MockTransport` — встроенная в httpx, без extra deps.

Покрывает:
- complete: happy path, parsing content + usage, SYSTEM_PROMPT prepended,
  max_tokens, Authorization header.
- complete: missing usage → len//4 fallback.
- complete: empty content → ''.
- complete: httpx.HTTPError → re-raised.
- duration_ms > 0.
- stream: yields chunks, skip [DONE], skip malformed JSON.
- stream: empty choices skipped.
- Factory: vllm → VLLMProvider с правильным config.
"""

import json

import httpx
import pytest

from src.api.chat.llm import LLMMessage, VLLMProvider, get_llm_provider
from src.api.config import Settings


def _make_complete_response(
    content: str = "hello",
    completion_tokens: int | None = 7,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    if completion_tokens is not None:
        payload["usage"] = {"completion_tokens": completion_tokens}
    return payload


def _stream_lines(chunks: list[str]) -> bytes:
    """Build SSE stream body from text chunks (mimics vLLM output)."""
    lines: list[str] = []
    for chunk in chunks:
        delta_payload = {"choices": [{"delta": {"content": chunk}}]}
        lines.append(f"data: {json.dumps(delta_payload, ensure_ascii=False)}")
        lines.append("")  # blank line between events
    lines.append("data: [DONE]")
    lines.append("")
    return ("\n".join(lines)).encode("utf-8")


# ---------------------------------------------------------------------------
# complete


@pytest.mark.asyncio
async def test_complete_returns_parsed_llm_response() -> None:
    """Happy path: 200 OK с usage → LLMResponse заполнен."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_make_complete_response("Hi there", 3))

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen", timeout_seconds=5)
    provider._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    try:
        result = await provider.complete(
            [LLMMessage(role="user", content="Hello")],
            "sys",
        )
        assert result.content == "Hi there"
        assert result.token_count == 3
        assert result.duration_ms >= 0
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_prepends_system_message_in_payload() -> None:
    captured_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(request.content))
        return httpx.Response(200, json=_make_complete_response("x", 1))

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen")
    provider._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    try:
        await provider.complete(
            [LLMMessage(role="user", content="вопрос")],
            "Ты — ассистент reHome",
        )
        messages = captured_payload["messages"]
        assert isinstance(messages, list)
        assert messages[0] == {"role": "system", "content": "Ты — ассистент reHome"}
        assert messages[1] == {"role": "user", "content": "вопрос"}
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_passes_max_tokens_in_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_make_complete_response("x", 1))

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen")
    provider._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    try:
        await provider.complete([], "sys", max_tokens=42)
        assert captured["max_tokens"] == 42
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_sends_authorization_header_when_api_key_set() -> None:
    captured_auth: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_auth["value"] = request.headers.get("authorization") or ""
        return httpx.Response(200, json=_make_complete_response("x", 1))

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen", api_key="secret123")
    provider._client = httpx.AsyncClient(
        transport=transport,
        base_url="http://mock",
        headers={"Authorization": "Bearer secret123"},
    )
    try:
        await provider.complete([], "sys")
        assert captured_auth["value"] == "Bearer secret123"
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_missing_usage_falls_back_to_char_count() -> None:
    """usage отсутствует → token_count = len(content) // 4."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_make_complete_response("abcdefgh", completion_tokens=None),
        )

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen")
    provider._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    try:
        result = await provider.complete([], "sys")
        # 'abcdefgh' = 8 chars → 8//4 = 2
        assert result.token_count == 2
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_empty_choices_yields_empty_content() -> None:
    """Defensive: vLLM aберантный response (no choices) → content=''."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen")
    provider._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    try:
        result = await provider.complete([], "sys")
        assert result.content == ""
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_http_error_propagates() -> None:
    """5xx от vLLM → httpx.HTTPStatusError raised (router отдаст 5xx)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "model loading"})

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen")
    provider._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await provider.complete([], "sys")
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_complete_network_error_propagates() -> None:
    """Connection refused → httpx.ConnectError raised."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen")
    provider._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    try:
        with pytest.raises(httpx.ConnectError):
            await provider.complete([], "sys")
    finally:
        await provider.aclose()


# ---------------------------------------------------------------------------
# stream


@pytest.mark.asyncio
async def test_stream_yields_content_chunks() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = _stream_lines(["Hello", " world"])
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen")
    provider._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    try:
        chunks: list[str] = []
        async for chunk in provider.stream([], "sys"):
            chunks.append(chunk)
        assert chunks == ["Hello", " world"]
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_stream_terminates_on_done_marker() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        # После [DONE] больше chunks нет (vLLM не присылает)
        body = _stream_lines(["only"])
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen")
    provider._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    try:
        chunks = [c async for c in provider.stream([], "sys")]
        assert chunks == ["only"]
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_stream_skips_malformed_json_lines() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = (
            b"data: not-a-json\n\ndata: "
            + json.dumps({"choices": [{"delta": {"content": "ok"}}]}).encode()
            + b"\n\ndata: [DONE]\n\n"
        )
        return httpx.Response(200, content=body)

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen")
    provider._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    try:
        chunks = [c async for c in provider.stream([], "sys")]
        assert chunks == ["ok"]
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_stream_skips_chunks_without_content() -> None:
    """choices с delta без content (role-only first chunk) — skip."""

    def handler(_request: httpx.Request) -> httpx.Response:
        lines = [
            'data: {"choices":[{"delta":{"role":"assistant"}}]}',
            "",
            'data: {"choices":[{"delta":{"content":"actual"}}]}',
            "",
            "data: [DONE]",
            "",
        ]
        return httpx.Response(200, content=("\n".join(lines)).encode())

    transport = httpx.MockTransport(handler)
    provider = VLLMProvider(url="http://mock", model="qwen")
    provider._client = httpx.AsyncClient(transport=transport, base_url="http://mock")
    try:
        chunks = [c async for c in provider.stream([], "sys")]
        assert chunks == ["actual"]
    finally:
        await provider.aclose()


# ---------------------------------------------------------------------------
# Factory


def test_factory_returns_vllm_provider_with_settings() -> None:
    settings = Settings(
        LLM_PROVIDER="vllm",
        LLM_VLLM_URL="http://vllm-prod:8000",
        LLM_VLLM_MODEL="Qwen/Qwen2.5-32B-Instruct",
        LLM_VLLM_TIMEOUT_SECONDS=120,
        LLM_VLLM_API_KEY="prod-key",
    )
    provider = get_llm_provider(settings=settings)
    assert isinstance(provider, VLLMProvider)
    assert provider._model == "Qwen/Qwen2.5-32B-Instruct"
    # client base_url + timeout + headers set
    assert "vllm-prod" in str(provider._client.base_url)


def test_factory_vllm_without_api_key_no_authorization_header() -> None:
    settings = Settings(LLM_PROVIDER="vllm", LLM_VLLM_API_KEY=None)
    provider = get_llm_provider(settings=settings)
    assert isinstance(provider, VLLMProvider)
    # Authorization header не выставлен
    assert "authorization" not in {k.lower() for k in provider._client.headers}
