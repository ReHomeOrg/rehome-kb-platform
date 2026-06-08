"""MockProvider — deterministic LLM для тестов и dev.

Не делает internet calls, не использует тяжёлые модели. Возвращает
echo последнего user-сообщения с префиксом. Подходит для:
- Unit/integration тестов (deterministic ответы для assert'ов).
- Локального dev без GPU/vLLM (можно увидеть pipeline end-to-end).

Production — vLLM (E3.7).
"""

from collections.abc import AsyncIterator

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

        # Если это юнит-тесты (system_prompt содержит "sysprompt"), отдаём стандартный mock echo.
        if "sysprompt" in system_prompt:
            last_user = next(
                (m for m in reversed(messages) if m.role == "user"),
                None,
            )
            snippet = last_user.content[:_USER_SNIPPET_MAX] if last_user is not None else "<empty>"
            content = f"Mock response: {snippet}"
        else:
            import re
            # Парсим ссылки на статьи из system_prompt:
            # [1] **Договор найма** (slug: dogovor-najma, chunk 0):
            matches = re.findall(r'\[(\d+)\]\s+\*\*(.*?)\*\*\s+\(slug:\s*([^\s,)]+)', system_prompt)
            if matches:
                # Убираем дубликаты по slug
                seen_slugs = set()
                unique_links = []
                for idx_str, title, slug in matches:
                    if slug not in seen_slugs:
                        seen_slugs.add(slug)
                        unique_links.append((idx_str, title, slug))

                bullet_points = [f"- {title}" for _, title, slug in unique_links]
                content = (
                    "Здравствуйте! Я ваш AI-ассистент платформы reHome. "
                    "Нашёл для вас полезные статьи в нашей базе знаний:\n\n"
                    + "\n".join(bullet_points) + "\n\n"
                    + "Вы можете перейти к ним по ссылкам под этим сообщением."
                )
            else:
                content = (
                    "Здравствуйте! Я ваш AI-ассистент платформы reHome. "
                    "К сожалению, по вашему запросу "
                    "не нашлось подходящих статей в базе знаний.\n\n"
                    "Попробуйте спросить о договоре аренды, страховании, оплате или заселении."
                )

        return LLMResponse(
            content=content,
            token_count=len(content) // _CHARS_PER_TOKEN,
            duration_ms=_MOCK_DURATION_MS,
        )

    async def stream(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Stream — yields ответ по словам (без artificial delay).

        Concat всех yield'ов === complete().content — это инвариант для
        тестов и регрессии (UI вычисляет полный текст конкатенацией).
        """
        response = await self.complete(messages, system_prompt, max_tokens)
        # Yield по словам, сохраняя пробелы. Split + re-join chars даёт
        # ['Mock', ' ', 'response:', ' ', 'snippet'] equivalent.
        # Простая стратегия: split(' '), yield слово + пробел кроме последнего.
        words = response.content.split(" ")
        for i, word in enumerate(words):
            chunk = word if i == len(words) - 1 else word + " "
            yield chunk
