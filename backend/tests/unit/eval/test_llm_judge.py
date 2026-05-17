"""Tests для LLMJudge (ADR-0013 §4).

Используется stub LLMProvider возвращающий заранее заданные Likert-строки.
Это позволяет тестировать:
- Parsing Likert 1..5 → нормализованный [0, 1].
- 4 метрики: answer_correctness, faithfulness, citation_accuracy
  (deterministic), refusal_correctness.
- Refusal оценивается ТОЛЬКО для off_topic / prompt_injection / pii_third_party категорий.
- LLM call failure → метрика становится None (runner не падает).
- Out-of-range Likert (например 7) → None.
- Malformed response (без digit) → None.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from src.api.chat.llm.base import LLMMessage, LLMProvider, LLMResponse
from src.eval.dataset import EvalPair
from src.eval.judge import JudgeInput, LLMJudge


@dataclass
class _StubProvider(LLMProvider):
    """LLMProvider возвращающий fixed responses из очереди."""

    responses: list[str]
    raise_on_call: bool = False
    call_count: int = 0

    async def complete(
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if self.raise_on_call:
            raise RuntimeError("simulated provider failure")
        self.call_count += 1
        idx = (self.call_count - 1) % len(self.responses)
        return LLMResponse(content=self.responses[idx], token_count=1, duration_ms=10)

    async def stream(  # type: ignore[override]
        self,
        messages: list[LLMMessage],
        system_prompt: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        # Not used by judge.
        raise NotImplementedError


def _make_pair(category: str = "simple_faq") -> EvalPair:
    return EvalPair(
        id="t-1",
        category=category,  # type: ignore[arg-type]
        scope="public_anonymous",
        question="Сколько составляет залог?",
        expected_answer="Залога нет, только сервисный платёж.",
        expected_citations=["article:rental-service-fee-policy"],
    )


@pytest.mark.asyncio
async def test_llm_judge_likert_normalization() -> None:
    """Likert 5 → 1.0, 3 → 0.5, 1 → 0.0."""
    # 3 calls: answer_correctness, faithfulness, refusal (skipped для simple_faq).
    # Только 2 LLM calls → ['5', '3'].
    provider = _StubProvider(responses=["5", "3"])
    judge = LLMJudge(provider=provider, model_name="test")
    scores = await judge.score(
        JudgeInput(
            pair=_make_pair(),
            actual_answer="Залога нет",
            actual_citations=["article:rental-service-fee-policy"],
        )
    )
    assert scores.answer_correctness == 1.0
    assert scores.faithfulness == 0.5
    assert scores.citation_accuracy == 1.0  # deterministic
    assert scores.refusal_correctness is None  # not refusal category
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_llm_judge_refusal_only_for_refusal_categories() -> None:
    """off_topic → 3 LLM calls (answer, faithfulness, refusal)."""
    provider = _StubProvider(responses=["1", "1", "5"])
    judge = LLMJudge(provider=provider, model_name="test")
    scores = await judge.score(
        JudgeInput(
            pair=_make_pair(category="off_topic"),
            actual_answer="Я не отвечаю на вопросы вне темы.",
            actual_citations=[],
        )
    )
    assert scores.answer_correctness == 0.0
    assert scores.faithfulness == 0.0
    assert scores.refusal_correctness == 1.0
    assert provider.call_count == 3


@pytest.mark.asyncio
async def test_llm_judge_parses_likert_amid_text() -> None:
    """Толерантно к minor format drift: 'Оценка: 4.' → 4."""
    provider = _StubProvider(responses=["Оценка: 4."])
    judge = LLMJudge(provider=provider, model_name="test")
    # Only first LLM call матчит — заодно тестим что одна цифра достаточна.
    scores = await judge.score(
        JudgeInput(
            pair=_make_pair(),
            actual_answer="ответ",
            actual_citations=[],
        )
    )
    assert scores.answer_correctness == 0.75


@pytest.mark.asyncio
async def test_llm_judge_out_of_range_returns_none() -> None:
    """Likert 7 (вне 1..5) → None (regex ловит только 1..5, всё остальное None)."""
    provider = _StubProvider(responses=["7", "9"])
    judge = LLMJudge(provider=provider, model_name="test")
    scores = await judge.score(
        JudgeInput(
            pair=_make_pair(),
            actual_answer="x",
            actual_citations=[],
        )
    )
    # Regex \b[1-5]\b не матчит "7" и "9" → None.
    assert scores.answer_correctness is None
    assert scores.faithfulness is None


@pytest.mark.asyncio
async def test_llm_judge_malformed_response_returns_none() -> None:
    """Ответ без digit → parsing fails → None для этой метрики."""
    provider = _StubProvider(responses=["abc", "no digit here"])
    judge = LLMJudge(provider=provider, model_name="test")
    scores = await judge.score(
        JudgeInput(
            pair=_make_pair(),
            actual_answer="x",
            actual_citations=[],
        )
    )
    assert scores.answer_correctness is None
    assert scores.faithfulness is None
    # citation_accuracy всё равно computed deterministically.
    assert scores.citation_accuracy is not None


@pytest.mark.asyncio
async def test_llm_judge_provider_error_returns_none() -> None:
    """LLM call raise → метрика None, runner не падает."""
    provider = _StubProvider(responses=[], raise_on_call=True)
    judge = LLMJudge(provider=provider, model_name="test")
    scores = await judge.score(
        JudgeInput(
            pair=_make_pair(),
            actual_answer="x",
            actual_citations=[],
        )
    )
    assert scores.answer_correctness is None
    assert scores.faithfulness is None
    # citation_accuracy не зависит от LLM.
    assert scores.citation_accuracy is not None


@pytest.mark.asyncio
async def test_llm_judge_composite_score_now_unblocked() -> None:
    """Когда все 4 метрики ≠ None, composite_score возвращает реальное число.

    Acceptance per ADR-0013: composite разблокируется как только LLMJudge
    подключён к provider'у. Это smoke-проверка end-to-end pipeline'а.
    """
    from src.eval.metrics import composite_score

    # 3 LLM calls для refusal category, все Likert=4 → 0.75 normalized.
    provider = _StubProvider(responses=["4"])
    judge = LLMJudge(provider=provider, model_name="test")
    scores = await judge.score(
        JudgeInput(
            pair=_make_pair(category="off_topic"),
            actual_answer="Не могу ответить.",
            actual_citations=[],
        )
    )
    assert scores.answer_correctness == 0.75
    assert scores.faithfulness == 0.75
    assert scores.citation_accuracy is not None
    assert scores.refusal_correctness == 0.75
    # Composite разблокирован — non-None.
    composite = composite_score(scores)
    assert composite is not None
    assert 0.0 <= composite <= 1.0
