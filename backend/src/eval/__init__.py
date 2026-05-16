"""Eval-стенд для LLM-провайдеров (ADR-0013, ТЗ §3 Чат-поиск).

Skeleton MVP — pipeline для прогона размеченного dataset'а через
`LLMProvider` и сбора метрик (latency, cost, citation accuracy).
LLMJudge — backlog, ждём landing'а второго провайдера.
"""

from src.eval.dataset import EvalCategory, EvalPair, EvalScope, load_dataset
from src.eval.metrics import EvalScores, citation_accuracy, composite_score, estimate_cost_rub
from src.eval.report import AggregateMetrics, EvalReport, PairResult

__all__ = [
    "AggregateMetrics",
    "EvalCategory",
    "EvalPair",
    "EvalReport",
    "EvalScope",
    "EvalScores",
    "PairResult",
    "citation_accuracy",
    "composite_score",
    "estimate_cost_rub",
    "load_dataset",
]
