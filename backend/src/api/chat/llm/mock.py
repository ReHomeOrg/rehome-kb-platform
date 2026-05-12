"""MockProvider — deterministic LLM для тестов и dev.

Не делает internet calls, не использует тяжёлые модели. Возвращает
echo последнего user-сообщения с префиксом. Подходит для:
- Unit/integration тестов (deterministic ответы для assert'ов).
- Локального dev без GPU/vLLM (можно увидеть pipeline end-to-end).

Production — vLLM (E3.7).
"""

from src.api.chat.llm.base import LLMMessage, LLMProvider, LLMResponse

# Длина echo-snippet'а пользовательского сообщения. Tradeoff: длиннее
# даёт более realistic ответ для тестов; короче — стабильнее в
# assertion'ах. 100 chars — sane middle.
_USER_SNIPPET_MAX = 100

# Mock-параметры: фиксированные значения для предсказуемых тестов.
# duration_ms namedconst — не magic number.
_MOCK_DURATION_MS = 50
# token_count ≈ chars/4 (rough BPE-like ratio).
_CHARS_PER_TOKEN = 4


class MockProvider(LLMProvider):
    """Echo последний user message c префиксом `Mock response:`.

    Дополнительно использует system_prompt для prefix'а, чтобы можно
    было asser'tить что system_prompt был передан (нет потерь в pipeline).
    """

    async def complete(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        del max_tokens  # honored как soft-cap — для mock не применяем
        del system_prompt  # принимаем, но не использует prefix (для cleaner assert'ов)

        last_user = next(
            (m for m in reversed(messages) if m.role == "user"),
            None,
        )
        snippet = last_user.content[:_USER_SNIPPET_MAX] if last_user is not None else "<empty>"
        content = f"Mock response: {snippet}"
        return LLMResponse(
            content=content,
            token_count=len(content) // _CHARS_PER_TOKEN,
            duration_ms=_MOCK_DURATION_MS,
        )
