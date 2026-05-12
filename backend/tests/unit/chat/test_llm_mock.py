"""Unit-тесты MockProvider (E3.3 #65).

Покрывает:
- Determinism: same input → same output.
- Echo последнего user message.
- Empty/no user messages → fallback content.
- token_count и duration_ms заполнены.
- system_prompt принимается без падения (но не влияет на output — для
  clean assertions; реальный provider должен использовать).
- max_tokens параметр accepted.
"""

import pytest

from src.api.chat.llm import LLMMessage, MockProvider


@pytest.mark.asyncio
async def test_mock_provider_deterministic_same_input_same_output() -> None:
    provider = MockProvider()
    messages = [LLMMessage(role="user", content="Привет, мир")]
    r1 = await provider.complete(messages, "sysprompt")
    r2 = await provider.complete(messages, "sysprompt")
    assert r1 == r2


@pytest.mark.asyncio
async def test_mock_provider_echoes_last_user_message() -> None:
    provider = MockProvider()
    messages = [
        LLMMessage(role="user", content="первый вопрос"),
        LLMMessage(role="assistant", content="первый ответ"),
        LLMMessage(role="user", content="ВТОРОЙ вопрос"),
    ]
    response = await provider.complete(messages, "sysprompt")
    assert "ВТОРОЙ вопрос" in response.content
    assert "первый" not in response.content


@pytest.mark.asyncio
async def test_mock_provider_no_user_messages_uses_fallback() -> None:
    provider = MockProvider()
    response = await provider.complete([], "sysprompt")
    assert "<empty>" in response.content


@pytest.mark.asyncio
async def test_mock_provider_only_assistant_messages_uses_fallback() -> None:
    provider = MockProvider()
    messages = [LLMMessage(role="assistant", content="hi")]
    response = await provider.complete(messages, "sysprompt")
    assert "<empty>" in response.content


@pytest.mark.asyncio
async def test_mock_provider_response_has_token_count_and_duration() -> None:
    provider = MockProvider()
    response = await provider.complete([LLMMessage(role="user", content="x")], "sysprompt")
    assert response.token_count > 0
    assert response.duration_ms > 0


@pytest.mark.asyncio
async def test_mock_provider_truncates_long_user_message() -> None:
    """Snippet ограничивается 100 chars."""
    provider = MockProvider()
    long_text = "a" * 500
    response = await provider.complete([LLMMessage(role="user", content=long_text)], "sysprompt")
    # `Mock response: ` (15 chars) + max 100 chars snippet
    assert len(response.content) <= 15 + 100


@pytest.mark.asyncio
async def test_mock_provider_accepts_max_tokens_kwarg() -> None:
    provider = MockProvider()
    response = await provider.complete(
        [LLMMessage(role="user", content="x")], "sysprompt", max_tokens=42
    )
    assert response.content.startswith("Mock response:")
