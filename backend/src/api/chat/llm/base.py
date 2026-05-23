"""LLMProvider abstract base + value-types для chat.

Frozen dataclasses для message/response — immutable, hashable, удобно
для memoization при будущем кэшировании.

ABC pattern позволяет подключить вторую реализацию (vLLM в E3.7,
GigaChat/YandexGPT теоретически в будущем) без правок в router.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

LLMRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    """Одно сообщение для conversation history.

    `role` — `system` (инструкция модели), `user` (вопрос), `assistant`
    (предыдущий ответ модели). Совпадает с chat_messages.role CHECK
    constraint enum.
    """

    role: LLMRole
    content: str


@dataclass(frozen=True)
class LLMResponse:
    """Ответ LLM на complete()."""

    content: str
    token_count: int
    duration_ms: int


class LLMProvider(ABC):
    """Абстрактный provider для LLM completions.

    Подкласс должен реализовать `complete` — async вызов модели с
    conversation history + system prompt → completion.

    Concrete adapters: `MockProvider` (тесты), `VLLMProvider` (self-host
    OpenAI-compat), `GigaChatProvider` (Sber), `YandexGptProvider`
    (Yandex Cloud). SSE streaming через `stream()` — все adapters
    делегируют base fallback ИЛИ override'ят с native streaming
    (vLLM делает real upstream chunking).
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Дёргает модель с conversation history + system prompt.

        `messages` уже включает текущий user message (last).
        `system_prompt` — отдельный first system-role параметр (provider'у
        решать, как его инжектить — обычно prepend как system message).
        `max_tokens` — soft cap на длину ответа.

        Raises: provider-specific exceptions (TimeoutError, RuntimeError).
        Router НЕ перехватывает — пусть всплывает 5xx (DB не тронута до
        этой точки, retry-safe).
        """
        raise NotImplementedError

    async def stream(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Yield response по частям (для SSE — E3.4 #67).

        Базовая реализация — fallback через `complete()`: provider'ы
        без native streaming yield'ят весь ответ одним chunk'ом. Vllm
        adapter (E3.7) override'нет с реальным upstream streaming.

        Retry-safety: caller (router) собирает chunks в memory list,
        вызывает `record_chat_turn` только после успешного завершения
        итератора. Exception здесь → mid-stream `event: error` без
        persist'а.
        """
        response = await self.complete(messages, system_prompt, max_tokens)
        yield response.content

    async def aclose(self) -> None:
        """Release underlying resources (httpx client pool и т.п.).

        Базовая реализация — no-op (для stateless providers типа
        MockProvider). Adapters с httpx.AsyncClient (vllm / gigachat /
        yandex_gpt) override'ят с `await self._client.aclose()`.

        Called from `factory.close_llm_provider` в FastAPI lifespan
        shutdown (#350).
        """
        return
