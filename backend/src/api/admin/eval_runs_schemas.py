"""Schemas для /admin/llm/eval-runs (#244, OpenAPI 04 §EvalRun)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EvalTestSet = Literal["full", "smoke", "custom"]
EvalRunStatus = Literal["RUNNING", "COMPLETED", "FAILED"]


class EvalRunStartRequest(BaseModel):
    """POST /admin/llm/eval-runs body (per OpenAPI 04 §startEvalRun).

    MVP scope:
    - `providers` — поддерживается только `["mock"]` пока real LLM
      credentials не сконфигурированы в env (см. ADR-0013).
    - `test_set` — поддерживается только `"smoke"` (built-in 10 pairs
      из tests/eval/golden.jsonl).
    - `custom_questions` — backlog; принимаем но игнорируем если
      test_set != "custom".
    """

    model_config = ConfigDict(extra="forbid")

    providers: list[str] = Field(min_length=1)
    test_set: EvalTestSet
    custom_questions: list[str] | None = Field(default=None, max_length=100)


class EvalRunStartResponse(BaseModel):
    """POST response (per OpenAPI 04)."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID


class EvalRunProviderResult(BaseModel):
    """Per-provider aggregated metrics в EvalRun.results[].

    OpenAPI 04 §EvalRun.results — все metric fields nullable (depend от
    того, был ли LLMJudge запущен). MVP без judge → composite_score /
    answer_correctness / faithfulness null'ы; citation_accuracy = avg
    из per_pair (deterministic).
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    composite_score: float | None = None
    answer_correctness: float | None = None
    faithfulness: float | None = None
    citation_accuracy: float | None = None
    refusal_correctness: float | None = None
    avg_latency_ms: int | None = None
    cost_per_query_rub: float | None = None


class EvalRunSummary(BaseModel):
    """OpenAPI 04 §EvalRun — projection из admin_tasks row."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    started_at: datetime
    completed_at: datetime | None = None
    status: EvalRunStatus
    providers: list[str] = Field(default_factory=list)
    test_set: str | None = None
    results: list[EvalRunProviderResult] = Field(default_factory=list)


class EvalRunListResponse(BaseModel):
    """GET /admin/llm/eval-runs response envelope."""

    model_config = ConfigDict(extra="forbid")

    data: list[EvalRunSummary]


__all__ = [
    "EvalRunListResponse",
    "EvalRunProviderResult",
    "EvalRunStartRequest",
    "EvalRunStartResponse",
    "EvalRunStatus",
    "EvalRunSummary",
    "EvalTestSet",
]
