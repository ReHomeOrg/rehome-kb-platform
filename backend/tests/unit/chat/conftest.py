"""Chat package fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.api.chat.llm import factory as _llm_factory


@pytest.fixture(autouse=True)
def _reset_llm_singleton() -> Iterator[None]:
    """Изолирует module-level LLM provider singleton между tests.

    Без этого fixture тесты, проверяющие dispatch `get_llm_provider`
    с разными LLM_PROVIDER settings, получат cached instance от
    предыдущего теста (#350 singleton lifecycle).
    """
    _llm_factory._llm_provider_instance = None
    yield
    _llm_factory._llm_provider_instance = None
