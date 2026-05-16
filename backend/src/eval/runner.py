"""Eval runner — async harness прогоняет провайдер на dataset (ADR-0013).

Не использует RAG retrieval в MVP — pair'у `question` отправляется напрямую
в `LLMProvider.complete(messages=[user], system_prompt=...)`. Это сильно
упрощает первую итерацию: измеряем чистое поведение модели на
question/expected_answer пары, без шумов от retrieval-качества.

Backlog: full eval pipeline должен включать retrieval (ТЗ §3) — иначе
citation_accuracy не измеряется адекватно. Сейчас citations = пустой
список actual'а (модель не зовёт инструменты), expected_citations
матчатся только если в `expected_answer` явно процитированы slug'и.
Это правда оценивается LLMJudge'ем (faithfulness, refusal), не текущим
deterministic harness'ом.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from src.api.chat.llm.base import LLMMessage, LLMProvider
from src.eval.dataset import EvalPair
from src.eval.judge import Judge, JudgeInput
from src.eval.metrics import EvalScores, composite_score, estimate_cost_rub
from src.eval.report import PairResult

logger = logging.getLogger(__name__)


# Default system prompt — мини-версия для P0.5 sandbox'а. Production
# system prompt живёт в `src/api/chat/system_prompt.py`; eval намеренно
# использует stripped-down версию, чтобы изолировать поведение модели
# от prompt-engineering changes.
DEFAULT_SYSTEM_PROMPT = (
    "Ты — ассистент платформы reHome. Отвечай кратко и опирайся только "
    "на проверенные источники. Если не знаешь — скажи об этом."
)

# `CitationExtractor` — функция, которая из ответа модели извлекает list
# of citation strings (slug'и/ID статей). MVP — заглушка возвращающая
# пустой список. Реальные provider'ы должны возвращать citations через
# отдельное поле в response — backlog ADR-0010 (RAG response shape).
CitationExtractor = Callable[[str], list[str]]


def _no_citations(_answer: str) -> list[str]:
    """MVP-default: модель не возвращает citations через text → empty list."""
    return []


async def run_one(
    pair: EvalPair,
    provider: LLMProvider,
    *,
    provider_name: str,
    judge: Judge | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    extract_citations: CitationExtractor = _no_citations,
) -> PairResult:
    """Прогон одной пары — wall-clock latency + LLM call + scoring.

    Exceptions от provider'а captured в `PairResult.error`, остальные
    поля заполняются дефолтами. Это позволяет не падать всему run'у
    из-за единичного timeout'а.
    """
    started = time.perf_counter()
    actual_answer = ""
    prompt_tokens = 0
    completion_tokens = 0
    error: str | None = None
    actual_citations: list[str] = []

    messages = [LLMMessage(role="user", content=pair.question)]
    try:
        response = await provider.complete(
            messages=messages,
            system_prompt=system_prompt,
        )
        actual_answer = response.content
        # LLMResponse имеет только `token_count` (total), не split.
        # Approximate: 60% prompt / 40% completion — типичный QA pattern.
        # Backlog: extend LLMResponse с prompt/completion split.
        completion_tokens = int(response.token_count * 0.4)
        prompt_tokens = response.token_count - completion_tokens
        actual_citations = extract_citations(actual_answer)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "eval.run_one.provider_error",
            extra={"pair_id": pair.id, "error": error},
        )

    latency = time.perf_counter() - started
    cost = estimate_cost_rub(provider_name, prompt_tokens, completion_tokens)

    # Scoring через Judge если передан. Errored pair — все None (без output'а
    # нечего оценивать).
    scores = EvalScores(
        answer_correctness=None,
        faithfulness=None,
        citation_accuracy=None,
        refusal_correctness=None,
    )
    if error is None and judge is not None:
        scores = await judge.score(
            JudgeInput(
                pair=pair,
                actual_answer=actual_answer,
                actual_citations=actual_citations,
            )
        )

    return PairResult(
        pair_id=pair.id,
        latency_seconds=latency,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_rub=cost,
        actual_answer=actual_answer,
        actual_citations=actual_citations,
        scores=scores,
        composite=composite_score(scores),
        error=error,
    )


async def run_dataset(
    pairs: list[EvalPair],
    provider: LLMProvider,
    *,
    provider_name: str,
    judge: Judge | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    extract_citations: CitationExtractor = _no_citations,
) -> list[PairResult]:
    """Прогоняет провайдер на всём dataset'е — sequential.

    НЕ parallel: rate-limits на real LLM API'ях легко триггернуть,
    и для MVP с 10 sample парами sequential — это секунды. Concurrent
    runner — backlog когда подключится реальный платный provider и
    будет нужно укладываться в budget.
    """
    results: list[PairResult] = []
    for i, pair in enumerate(pairs, start=1):
        logger.info(
            "eval.runner.processing",
            extra={"pair_index": i, "pair_total": len(pairs), "pair_id": pair.id},
        )
        result = await run_one(
            pair,
            provider,
            provider_name=provider_name,
            judge=judge,
            system_prompt=system_prompt,
            extract_citations=extract_citations,
        )
        results.append(result)
    return results
