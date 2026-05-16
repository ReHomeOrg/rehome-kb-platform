"""Unit tests для eval/runner.py — провайдер моком, latency измеряется."""

from __future__ import annotations

import pytest

from src.api.chat.llm.base import LLMMessage, LLMProvider, LLMResponse
from src.eval.dataset import EvalPair
from src.eval.runner import run_dataset, run_one


class _FakeProvider(LLMProvider):
    """Async fake — возвращает fixed response с заданным token count."""

    def __init__(self, content: str = "ответ", token_count: int = 100) -> None:
        self._content = content
        self._token_count = token_count

    async def complete(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        return LLMResponse(content=self._content, token_count=self._token_count, duration_ms=5)


class _RaisingProvider(LLMProvider):
    async def complete(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        raise RuntimeError("provider exploded")


def _pair(id_: str = "p1") -> EvalPair:
    return EvalPair(
        id=id_,
        category="simple_faq",
        scope="public_anonymous",
        question="Сколько составляет залог?",
        expected_answer="Залога нет",
        expected_citations=["article:rental-service-fee-policy"],
    )


@pytest.mark.asyncio
async def test_run_one_happy_path() -> None:
    provider = _FakeProvider(content="Залога нет", token_count=200)
    result = await run_one(_pair(), provider, provider_name="mock")
    assert result.pair_id == "p1"
    assert result.error is None
    assert result.actual_answer == "Залога нет"
    assert result.prompt_tokens + result.completion_tokens == 200
    assert result.latency_seconds > 0
    # MVP: только citation_accuracy computable.
    assert result.scores.citation_accuracy is not None
    assert result.scores.answer_correctness is None
    # composite = None в MVP.
    assert result.composite is None


@pytest.mark.asyncio
async def test_run_one_provider_exception_captured() -> None:
    """Exception от provider'а → PairResult.error, не raise."""
    result = await run_one(_pair(), _RaisingProvider(), provider_name="mock")
    assert result.error is not None
    assert "RuntimeError" in result.error
    assert "provider exploded" in result.error
    assert result.actual_answer == ""
    assert result.scores.citation_accuracy is None  # без ответа нет scoring


@pytest.mark.asyncio
async def test_run_one_uses_custom_citation_extractor() -> None:
    def extract(answer: str) -> list[str]:
        return ["article:rental-service-fee-policy"] if "Залога" in answer else []

    provider = _FakeProvider(content="Залога нет")
    result = await run_one(
        _pair(),
        provider,
        provider_name="mock",
        extract_citations=extract,
    )
    assert result.actual_citations == ["article:rental-service-fee-policy"]
    assert result.scores.citation_accuracy == 1.0


@pytest.mark.asyncio
async def test_run_dataset_processes_all_pairs_sequentially() -> None:
    pairs = [_pair(f"p{i}") for i in range(3)]
    provider = _FakeProvider()
    results = await run_dataset(pairs, provider, provider_name="mock")
    assert len(results) == 3
    assert [r.pair_id for r in results] == ["p0", "p1", "p2"]
