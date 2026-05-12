"""Unit-тесты LLMProvider.stream + MockProvider.stream (E3.4 #67)."""

from collections.abc import AsyncIterator

import pytest

from src.api.chat.llm import LLMMessage, MockProvider
from src.api.chat.llm.base import LLMProvider, LLMResponse


@pytest.mark.asyncio
async def test_mock_stream_yields_chunks() -> None:
    provider = MockProvider()
    chunks: list[str] = []
    async for c in provider.stream([LLMMessage(role="user", content="hello")], "sys"):
        chunks.append(c)
    assert len(chunks) > 1


@pytest.mark.asyncio
async def test_mock_stream_concat_equals_complete_content() -> None:
    """Инвариант: concat всех stream chunks == complete().content."""
    provider = MockProvider()
    messages = [LLMMessage(role="user", content="один два три")]
    complete_response = await provider.complete(messages, "sys")
    streamed_chunks: list[str] = []
    async for c in provider.stream(messages, "sys"):
        streamed_chunks.append(c)
    assert "".join(streamed_chunks) == complete_response.content


@pytest.mark.asyncio
async def test_mock_stream_preserves_word_boundaries() -> None:
    """Каждый chunk — слово или слово+пробел."""
    provider = MockProvider()
    chunks: list[str] = []
    async for c in provider.stream([LLMMessage(role="user", content="one two three")], "sys"):
        chunks.append(c)
    # Все chunks кроме последнего заканчиваются пробелом
    for chunk in chunks[:-1]:
        assert chunk.endswith(" ")


@pytest.mark.asyncio
async def test_default_stream_fallback_yields_single_chunk() -> None:
    """Default `LLMProvider.stream` (без override) — 1 chunk через complete()."""

    class _NonStreamingProvider(LLMProvider):
        async def complete(
            self,
            messages: list[LLMMessage],  # noqa: ARG002
            system_prompt: str,  # noqa: ARG002
            max_tokens: int = 1024,  # noqa: ARG002
        ) -> LLMResponse:
            return LLMResponse(content="single", token_count=1, duration_ms=10)

    provider = _NonStreamingProvider()
    chunks: list[str] = []
    async for c in provider.stream([], "sys"):
        chunks.append(c)
    assert chunks == ["single"]


@pytest.mark.asyncio
async def test_mock_stream_accepts_max_tokens_kwarg() -> None:
    provider = MockProvider()

    async def _consume(it: AsyncIterator[str]) -> list[str]:
        return [c async for c in it]

    chunks = await _consume(
        provider.stream([LLMMessage(role="user", content="x")], "sys", max_tokens=42)
    )
    assert len(chunks) > 0
