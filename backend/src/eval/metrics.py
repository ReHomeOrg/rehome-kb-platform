"""Eval metrics — latency, cost, citation accuracy, composite score (ADR-0013 §5).

Composite формула per ТЗ §3.5:

    composite = answer_correctness × 0.4
              + faithfulness × 0.3
              + citation_accuracy × 0.2
              + refusal_correctness × 0.1

В MVP без LLMJudge — только `citation_accuracy` computed deterministically.
Остальные три = `None`, composite_score → `None`. См. ADR-0013 §3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class EvalScores:
    """Скоры одной пары. `None` если метрика не computable в текущей конфигурации.

    `citation_accuracy` всегда computable (deterministic), остальные —
    backlog (зависят от LLMJudge).
    """

    answer_correctness: float | None
    faithfulness: float | None
    citation_accuracy: float | None
    refusal_correctness: float | None


# Composite weights по ТЗ §3.5. Сумма = 1.0 — invariant'но проверено в тестах.
_COMPOSITE_WEIGHTS: Final[dict[str, float]] = {
    "answer_correctness": 0.4,
    "faithfulness": 0.3,
    "citation_accuracy": 0.2,
    "refusal_correctness": 0.1,
}


def composite_score(scores: EvalScores) -> float | None:
    """Композитный score — `None` если хотя бы одна метрика отсутствует.

    Намеренно без partial fallback: лучше явный `None` чем "compute 3 of 4
    and pretend score is final". Decision'ы по провайдеру требуют всех
    4 метрик (см. ADR-0013 §3).
    """
    values = {
        "answer_correctness": scores.answer_correctness,
        "faithfulness": scores.faithfulness,
        "citation_accuracy": scores.citation_accuracy,
        "refusal_correctness": scores.refusal_correctness,
    }
    if any(v is None for v in values.values()):
        return None
    return sum(_COMPOSITE_WEIGHTS[k] * v for k, v in values.items() if v is not None)


def citation_accuracy(actual: list[str], expected: list[str]) -> float:
    """Доля expected citations найденных в actual (intersection / expected).

    Пустой `expected` → 1.0 (например, off_topic пары без cited sources).
    Order и duplicate'ы игнорируются — set semantics.

    Это deterministic метрика — никаких LLM-judge вызовов.
    """
    expected_set = set(expected)
    if not expected_set:
        return 1.0
    actual_set = set(actual)
    return len(actual_set & expected_set) / len(expected_set)


# Provider name → (rate per 1M prompt tokens, rate per 1M output tokens) в рублях.
# Hardcoded таблица — пока LLMProvider abstraction не expose'ит cost.
# Backlog (ADR-0013): переместить в `LLMProvider.cost_per_1m_*` fields,
# когда добавится поле в base class. Сейчас держим здесь чтобы не блокировать
# eval pipeline на refactor'е chat module'а.
_PROVIDER_RATES_RUB: Final[dict[str, tuple[float, float]]] = {
    # MockProvider — 0 cost (детерминистский, fake).
    "mock": (0.0, 0.0),
    # vLLM self-hosted — 0 marginal cost (electricity не считаем),
    # для honest comparison vs API провайдеров — отдельная задача.
    "vllm": (0.0, 0.0),
    # YandexGPT Pro ставки на 2026-05 (placeholder, проверить перед merge'ом
    # production-decisions report).
    "yandexgpt_pro": (1200.0, 1200.0),
    # GigaChat Pro ставки на 2026-05 (placeholder).
    "gigachat_pro": (1500.0, 1500.0),
}


def estimate_cost_rub(
    provider_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Cost estimate в рублях. Returns 0.0 для unknown провайдера.

    Не raise'ит на unknown — eval pipeline тестируется с MockProvider,
    fallback к 0.0 безопасный default. Production decision'ы должны
    проверять что _PROVIDER_RATES_RUB содержит ставку (если 0 — recheck).
    """
    rate_prompt, rate_completion = _PROVIDER_RATES_RUB.get(provider_name, (0.0, 0.0))
    return (prompt_tokens / 1_000_000) * rate_prompt + (
        completion_tokens / 1_000_000
    ) * rate_completion


def percentile(values: list[float], p: float) -> float:
    """Простой percentile без numpy — interpolate между sorted indices.

    `p` ∈ [0, 1]. Пустой list → 0.0 (defensive, не raise — eval может
    запускаться на empty selection).
    """
    if not values:
        return 0.0
    if p < 0 or p > 1:
        raise ValueError(f"percentile p должен быть в [0, 1], got {p}")
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = p * (len(sorted_vals) - 1)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac
