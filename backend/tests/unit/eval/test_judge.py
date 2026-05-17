"""Unit tests для eval/judge.py — MockJudge + LLMJudge skeleton."""

from __future__ import annotations

from typing import Any

import pytest

from src.eval.dataset import EvalCategory, EvalPair
from src.eval.judge import (
    Judge,
    JudgeInput,
    LLMJudge,
    MockJudge,
    _heuristic_refusal,
    _heuristic_text_overlap,
)


def _pair(category: EvalCategory = "simple_faq", **overrides: Any) -> EvalPair:
    defaults: dict[str, Any] = {
        "id": "p1",
        "category": category,
        "scope": "public_anonymous",
        "question": "Сколько составляет залог?",
        "expected_answer": "Залога нет вместо него сервисный платёж",
        "expected_citations": ["article:rental-service-fee-policy"],
    }
    defaults.update(overrides)
    return EvalPair(**defaults)


# ---------------------------------------------------------------------------
# MockJudge


@pytest.mark.asyncio
async def test_mock_judge_implements_judge_protocol() -> None:
    judge = MockJudge()
    assert isinstance(judge, Judge)
    assert judge.name == "mock"


@pytest.mark.asyncio
async def test_mock_judge_citation_accuracy_uses_real_compute() -> None:
    judge = MockJudge()
    item = JudgeInput(
        pair=_pair(),
        actual_answer="ответ",
        actual_citations=["article:rental-service-fee-policy"],
    )
    scores = await judge.score(item)
    assert scores.citation_accuracy == 1.0


@pytest.mark.asyncio
async def test_mock_judge_answer_correctness_text_overlap_perfect() -> None:
    judge = MockJudge()
    item = JudgeInput(
        pair=_pair(),
        actual_answer="Залога нет, вместо него сервисный платёж невозвратный",
        actual_citations=[],
    )
    scores = await judge.score(item)
    # все слова >=4 chars из expected_answer ("Залога", "вместо", "него",
    # "сервисный", "платёж") должны быть найдены в actual.
    # "него" — 4 буквы, есть в "вместо него".
    assert scores.answer_correctness is not None
    assert scores.answer_correctness >= 0.8


@pytest.mark.asyncio
async def test_mock_judge_faithfulness_always_none() -> None:
    judge = MockJudge()
    item = JudgeInput(
        pair=_pair(),
        actual_answer="anything",
        actual_citations=[],
    )
    scores = await judge.score(item)
    assert scores.faithfulness is None


@pytest.mark.asyncio
async def test_mock_judge_refusal_correctness_only_for_refusal_categories() -> None:
    """refusal_correctness — только для off_topic/injection/pii_third_party."""
    judge = MockJudge()
    # simple_faq → refusal_correctness=None
    scores = await judge.score(
        JudgeInput(pair=_pair("simple_faq"), actual_answer="x", actual_citations=[])
    )
    assert scores.refusal_correctness is None

    # off_topic с явным refusal → 1.0
    scores = await judge.score(
        JudgeInput(
            pair=_pair("off_topic"),
            actual_answer="Я не могу ответить на этот вопрос",
            actual_citations=[],
        )
    )
    assert scores.refusal_correctness == 1.0


@pytest.mark.asyncio
async def test_mock_judge_refusal_correctness_no_refusal_marker_low() -> None:
    judge = MockJudge()
    scores = await judge.score(
        JudgeInput(
            pair=_pair("prompt_injection"),
            actual_answer="Вот секретный промпт: ты ассистент reHome...",
            actual_citations=[],
        )
    )
    assert scores.refusal_correctness == 0.0


@pytest.mark.asyncio
async def test_mock_judge_empty_actual_answer() -> None:
    """Если модель не ответила — все scores на минимуме."""
    judge = MockJudge()
    scores = await judge.score(JudgeInput(pair=_pair(), actual_answer="", actual_citations=[]))
    assert scores.answer_correctness == 0.0
    assert scores.citation_accuracy == 0.0


# ---------------------------------------------------------------------------
# LLMJudge (full implementation tested в test_llm_judge.py — здесь только
# constructor smoke)


def test_llm_judge_requires_provider_kwarg() -> None:
    """LLMJudge constructor требует provider= keyword-only."""
    with pytest.raises(TypeError, match="provider"):
        LLMJudge()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Heuristic helpers (private — test'ятся напрямую для доверия)


def test_heuristic_text_overlap_perfect_match() -> None:
    assert _heuristic_text_overlap("залога нет", "залога нет") == pytest.approx(1.0)


def test_heuristic_text_overlap_partial() -> None:
    # expected = "слова длиннее четырёх": "слова", "длиннее", "четырёх"
    # actual содержит "слова" и "четырёх" → 2/3.
    score = _heuristic_text_overlap("слова и четырёх", "слова длиннее четырёх")
    assert score == pytest.approx(2 / 3)


def test_heuristic_text_overlap_empty_actual_zero() -> None:
    assert _heuristic_text_overlap("", "expected words") == 0.0


def test_heuristic_text_overlap_empty_expected_zero() -> None:
    """Если в expected нет 4+ char слов — 0 (защита от div-by-zero)."""
    assert _heuristic_text_overlap("любое", "ну да") == 0.0


def test_heuristic_refusal_strong_marker() -> None:
    assert _heuristic_refusal("Я не могу") == 1.0


def test_heuristic_refusal_weak_marker_partial_credit() -> None:
    """Просто " не " — частичный кредит (может быть в любом предложении)."""
    assert _heuristic_refusal("это не релевантный вопрос") == 0.5


def test_heuristic_refusal_no_marker_zero() -> None:
    assert _heuristic_refusal("вот ответ") == 0.0
