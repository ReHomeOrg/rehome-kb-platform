"""Unit tests для eval/metrics.py."""

from __future__ import annotations

import pytest

from src.eval.metrics import (
    EvalScores,
    citation_accuracy,
    composite_score,
    estimate_cost_rub,
    percentile,
)

# ---------------------------------------------------------------------------
# citation_accuracy


def test_citation_accuracy_full_overlap() -> None:
    assert citation_accuracy(["a", "b", "c"], ["a", "b", "c"]) == 1.0


def test_citation_accuracy_partial() -> None:
    assert citation_accuracy(["a", "b"], ["a", "b", "c"]) == pytest.approx(2 / 3)


def test_citation_accuracy_no_overlap() -> None:
    assert citation_accuracy(["x"], ["a", "b"]) == 0.0


def test_citation_accuracy_empty_expected_is_perfect() -> None:
    """off_topic / refusal пары не имеют expected citations — score 1.0."""
    assert citation_accuracy([], []) == 1.0
    assert citation_accuracy(["irrelevant"], []) == 1.0


def test_citation_accuracy_dedups_via_set_semantics() -> None:
    """Duplicate'ы в actual игнорируются (set semantics)."""
    assert citation_accuracy(["a", "a", "a"], ["a", "b"]) == 0.5


# ---------------------------------------------------------------------------
# composite_score


def test_composite_score_all_metrics_present() -> None:
    s = EvalScores(
        answer_correctness=1.0,
        faithfulness=1.0,
        citation_accuracy=1.0,
        refusal_correctness=1.0,
    )
    assert composite_score(s) == pytest.approx(1.0)


def test_composite_score_weighted_formula() -> None:
    """Verify ТЗ §3.5 weights."""
    s = EvalScores(
        answer_correctness=0.5,
        faithfulness=0.0,
        citation_accuracy=1.0,
        refusal_correctness=0.0,
    )
    # 0.5*0.4 + 0.0*0.3 + 1.0*0.2 + 0.0*0.1 = 0.4
    assert composite_score(s) == pytest.approx(0.4)


def test_composite_score_returns_none_if_any_missing() -> None:
    """MVP-инвариант: при отсутствии LLMJudge'а composite всегда None."""
    s = EvalScores(
        answer_correctness=None,
        faithfulness=1.0,
        citation_accuracy=1.0,
        refusal_correctness=1.0,
    )
    assert composite_score(s) is None


def test_composite_score_mvp_state_returns_none() -> None:
    """Реалистичный MVP scenario — только citation computed."""
    s = EvalScores(
        answer_correctness=None,
        faithfulness=None,
        citation_accuracy=0.9,
        refusal_correctness=None,
    )
    assert composite_score(s) is None


# ---------------------------------------------------------------------------
# estimate_cost_rub


def test_estimate_cost_rub_known_provider() -> None:
    # yandexgpt_pro: 1200 ₽/1M input, 1200 ₽/1M output. 1000 input + 500 output.
    cost = estimate_cost_rub("yandexgpt_pro", 1000, 500)
    assert cost == pytest.approx((1000 / 1_000_000) * 1200 + (500 / 1_000_000) * 1200)


def test_estimate_cost_rub_mock_is_zero() -> None:
    assert estimate_cost_rub("mock", 10_000, 10_000) == 0.0


def test_estimate_cost_rub_unknown_provider_returns_zero() -> None:
    """Defensive: unknown name → 0.0, не raise (CI с MockProvider не падает)."""
    assert estimate_cost_rub("not_real", 1000, 500) == 0.0


# ---------------------------------------------------------------------------
# percentile


def test_percentile_empty_list_returns_zero() -> None:
    assert percentile([], 0.5) == 0.0


def test_percentile_single_value() -> None:
    assert percentile([42.0], 0.95) == 42.0


def test_percentile_p50_median() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == pytest.approx(3.0)


def test_percentile_p95_interpolated() -> None:
    """Linear interpolation: p=0.95 of [1..10] (0-indexed) = idx 9*0.95 = 8.55,
    floor=8, ceil=9 → 0.45*sorted[8] + 0.55*sorted[9] = 0.45*9 + 0.55*10 = 9.55."""
    result = percentile(list(range(1, 11)), 0.95)
    # values [1..10], k = 0.95 * 9 = 8.55, lo=8 → 9, hi=9 → 10, frac=0.55
    assert result == pytest.approx(9 * 0.45 + 10 * 0.55)


def test_percentile_invalid_p_raises() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        percentile([1.0], 1.5)


def test_percentile_sorted_invariant() -> None:
    """Input order не влияет на результат."""
    assert percentile([3.0, 1.0, 2.0], 0.5) == percentile([1.0, 2.0, 3.0], 0.5)
