"""Eval-runs service (#244).

Wraps `src/eval/runner.py` для запуска через admin API. MVP scope:
mock provider, smoke test_set, sync execution. Real provider config
landит когда credentials появятся в env (см. ADR-0013).

Storage model: aggregate per-provider results хранятся inline в
`admin_task.params['results']`. Per-pair details НЕ хранятся (CSV
report cap ~10KB на 10 pairs × 5 providers — ОК для JSONB; per_pair
с ответами модели — backlog когда landит MinIO blob storage).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.api.admin.eval_runs_schemas import (
    EvalRunProviderResult,
    EvalRunStartRequest,
    EvalRunSummary,
)
from src.api.admin.tasks_models import AdminTask
from src.api.admin.tasks_repository import AdminTaskRepository
from src.api.chat.llm.mock import MockProvider
from src.eval.dataset import load_dataset
from src.eval.report import aggregate_results
from src.eval.runner import run_dataset

logger = logging.getLogger(__name__)

# Currently supported providers — только те что не требуют real
# credentials в CI (mock — deterministic, без internet'а). Когда реальные
# provider creds сконфигурятся через env, mapping расширится через
# `_build_provider`.
_ALLOWED_PROVIDERS: frozenset[str] = frozenset({"mock"})

# Built-in smoke dataset path. Полный golden.jsonl — 45 pairs; smoke
# берёт первые 10 для quick admin UI runs (< 5s execution).
_SMOKE_DATASET_PATH = Path(__file__).resolve().parents[3] / "tests" / "eval" / "golden.jsonl"
_SMOKE_DATASET_LIMIT = 10


class EvalRunValidationError(ValueError):
    """422-mapped error: invalid request payload."""


class EvalRunsService:
    """Executes eval runs + projects admin_tasks rows to OpenAPI shape."""

    def __init__(self, task_repo: AdminTaskRepository) -> None:
        self._task_repo = task_repo

    async def start_run(
        self,
        request: EvalRunStartRequest,
        *,
        actor_sub: str,
    ) -> AdminTask:
        """Validate + create admin_task + execute synchronously.

        Real async execution — backlog (см. CS.11 admin_tasks async worker).
        """
        self._validate(request)
        pairs = self._load_pairs(request)

        task = await self._task_repo.create(
            type_="eval_run",
            actor_sub=actor_sub,
            params={
                "providers": request.providers,
                "test_set": request.test_set,
                "pair_count": len(pairs),
            },
        )
        await self._task_repo.mark_running(task.id)

        try:
            results = await self._execute_per_provider(request.providers, pairs)
        except Exception as exc:
            logger.exception("eval_run.execution_failed", extra={"task_id": str(task.id)})
            await self._task_repo.mark_failed(task.id, error=str(exc))
            raise

        # Merge results back в params для GET retrieval.
        # Merge через _refresh-pattern: read row, update JSONB, flush.
        row = await self._task_repo.get(task.id)
        if row is not None:
            row.params = {**row.params, "results": [r.model_dump() for r in results]}
        await self._task_repo.mark_completed(task.id)
        return task

    @staticmethod
    def _validate(request: EvalRunStartRequest) -> None:
        unknown = set(request.providers) - _ALLOWED_PROVIDERS
        if unknown:
            raise EvalRunValidationError(
                f"Unsupported providers: {sorted(unknown)}. Allowed: {sorted(_ALLOWED_PROVIDERS)}"
            )
        if request.test_set == "custom":
            raise EvalRunValidationError("test_set='custom' not yet supported; use 'smoke'")
        if request.test_set == "full":
            raise EvalRunValidationError("test_set='full' not yet supported; use 'smoke'")

    def _load_pairs(self, request: EvalRunStartRequest) -> list[Any]:
        """Smoke = первые 10 pair'ов из golden dataset (deterministic)."""
        del request  # test_set validated; пока всегда smoke.
        all_pairs = load_dataset(_SMOKE_DATASET_PATH)
        return all_pairs[:_SMOKE_DATASET_LIMIT]

    @staticmethod
    async def _execute_per_provider(
        providers: list[str],
        pairs: list[Any],
    ) -> list[EvalRunProviderResult]:
        """Запускает eval per provider, aggregates result в OpenAPI shape."""
        results: list[EvalRunProviderResult] = []
        for provider_name in providers:
            # Currently только mock — _validate уже отфильтровал остальное.
            provider = MockProvider()
            pair_results = await run_dataset(pairs, provider, provider_name=provider_name)
            agg = aggregate_results(pair_results)
            results.append(
                EvalRunProviderResult(
                    provider=provider_name,
                    composite_score=agg.composite_avg,
                    citation_accuracy=agg.citation_accuracy_avg,
                    avg_latency_ms=int(agg.latency_p50 * 1000),
                    cost_per_query_rub=agg.cost_per_query_avg,
                    # answer_correctness / faithfulness / refusal_correctness
                    # требуют LLMJudge — null до landing'а judge integration.
                )
            )
        return results

    @staticmethod
    def project_to_summary(row: AdminTask) -> EvalRunSummary:
        """Project admin_task row → OpenAPI 04 §EvalRun."""
        params = row.params or {}
        raw_results = params.get("results", [])
        results = [EvalRunProviderResult.model_validate(r) for r in raw_results]
        status = _status_to_eval_run(row.status)
        return EvalRunSummary(
            id=row.id,
            started_at=row.created_at,
            completed_at=row.completed_at,
            status=status,
            providers=params.get("providers", []),
            test_set=params.get("test_set"),
            results=results,
        )


def _status_to_eval_run(admin_task_status: str) -> Any:
    """Map admin_task status → OpenAPI §EvalRun status enum.

    OpenAPI: RUNNING | COMPLETED | FAILED.
    admin_tasks adds PENDING / CANCELLED. PENDING → RUNNING (UI shows
    как running до actual execution; в нашем sync MVP это buffer < 1s).
    CANCELLED → FAILED.
    """
    if admin_task_status in ("PENDING", "RUNNING"):
        return "RUNNING"
    if admin_task_status == "COMPLETED":
        return "COMPLETED"
    return "FAILED"


# Module-level constant export для тестов.
ALLOWED_PROVIDERS = _ALLOWED_PROVIDERS


__all__ = ["ALLOWED_PROVIDERS", "EvalRunValidationError", "EvalRunsService"]
