"""LLMProvider abstract base + value-types для chat.

Frozen dataclasses для message/response — immutable, hashable, удобно
для memoization при будущем кэшировании.

ABC pattern позволяет подключить вторую реализацию (vLLM в E3.7,
GigaChat/YandexGPT теоретически в будущем) без правок в router.
"""

from abc import ABC, abstractmethod
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

    **TODO для E3.7 (vLLM)**: complete() для vLLM будет занимать
    секунды. Текущий E3.3 router держит DB-транзакцию через record_chat_turn
    ПОСЛЕ LLM call — это безопасно (LLM exception → no DB write).
    При переходе на SSE (E3.4) — стриминг chunks без полного complete'а.
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
