"""Eval report — JSON структура output'а (ADR-0013 §6).

Не commit'ить reports в git (см. .gitignore `reports/`). Each run produces
a new file; decisions reference конкретный report file через commit'ы.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.eval.metrics import EvalScores, percentile


@dataclass
class PairResult:
    """Результат прогона одной пары через provider.

    `actual_*` — фактический output модели.
    `scores` — оценки (citation_accuracy computed; остальные None пока
    LLMJudge не подключён).
    """

    pair_id: str
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    cost_rub: float
    actual_answer: str
    actual_citations: list[str]
    scores: EvalScores
    composite: float | None
    error: str | None = None  # provider exception captured (если был)


@dataclass
class AggregateMetrics:
    """Aggregate по всему run'у — то что покажет дашборд."""

    pair_count: int
    error_count: int
    latency_p50: float
    latency_p95: float
    cost_per_query_avg: float
    citation_accuracy_avg: float
    composite_avg: float | None


@dataclass
class EvalReport:
    """Полный output одного run'а — сохраняется в JSON."""

    run_id: str
    run_started_at: str  # ISO 8601 UTC
    provider: str
    judge: str
    dataset_path: str
    dataset_sha256: str
    per_pair: list[PairResult]
    aggregate: AggregateMetrics

    def to_json(self) -> str:
        """JSON serialization с indent=2 для читаемости в git diff'ах
        (если decision-comment'ом будет приложен сниппет)."""

        def _default(o: Any) -> Any:
            if hasattr(o, "__dict__"):
                return o.__dict__
            return str(o)

        return json.dumps(asdict(self), indent=2, ensure_ascii=False, default=_default)

    def save(self, out_path: Path) -> None:
        """Атомарная запись — temp file + rename, чтобы partial CI cancel
        не оставил corrupt JSON."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp.write_text(self.to_json(), encoding="utf-8")
        tmp.rename(out_path)


def aggregate_results(pair_results: list[PairResult]) -> AggregateMetrics:
    """Pure-function aggregator — testable без Provider/Judge.

    `composite_avg` = `None` если ни у одной пары composite не computed
    (т.е. в MVP пока LLMJudge не подключён — всегда None).
    """
    successful = [p for p in pair_results if p.error is None]
    latencies = [p.latency_seconds for p in successful]
    costs = [p.cost_rub for p in successful]
    citation_scores = [
        p.scores.citation_accuracy for p in successful if p.scores.citation_accuracy is not None
    ]
    composites = [p.composite for p in successful if p.composite is not None]

    return AggregateMetrics(
        pair_count=len(pair_results),
        error_count=len(pair_results) - len(successful),
        latency_p50=percentile(latencies, 0.5),
        latency_p95=percentile(latencies, 0.95),
        cost_per_query_avg=sum(costs) / len(costs) if costs else 0.0,
        citation_accuracy_avg=sum(citation_scores) / len(citation_scores)
        if citation_scores
        else 0.0,
        composite_avg=sum(composites) / len(composites) if composites else None,
    )


def new_report(
    *,
    provider: str,
    judge: str,
    dataset_path: Path,
    dataset_sha256: str,
    per_pair: list[PairResult],
) -> EvalReport:
    """Factory — создаёт report с run_id + timestamp + aggregated metrics."""
    return EvalReport(
        run_id=str(uuid4()),
        run_started_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        provider=provider,
        judge=judge,
        dataset_path=str(dataset_path),
        dataset_sha256=dataset_sha256,
        per_pair=per_pair,
        aggregate=aggregate_results(per_pair),
    )


__all__ = [
    "AggregateMetrics",
    "EvalReport",
    "PairResult",
    "aggregate_results",
    "new_report",
]
