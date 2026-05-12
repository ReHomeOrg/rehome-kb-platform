"""LLMProvider abstraction для chat (E3 эпик).

В этом эпике (E3.3) реализован только `MockProvider` для тестов и dev.
Production vLLM adapter — E3.7.

Selection через `LLM_PROVIDER` env (default 'mock').
"""

from src.api.chat.llm.base import LLMMessage, LLMProvider, LLMResponse
from src.api.chat.llm.factory import get_llm_provider
from src.api.chat.llm.mock import MockProvider

__all__ = [
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "MockProvider",
    "get_llm_provider",
]
