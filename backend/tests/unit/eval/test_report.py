"""Unit tests для eval/report.py — serialization, aggregation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.eval.metrics import EvalScores
from src.eval.report import (
    PairResult,
    aggregate_results,
    new_report,
)


def _result(
    pair_id: str = "p1",
    latency: float = 0.1,
    citation: float | None = 1.0,
    error: str | None = None,
) -> PairResult:
    return PairResult(
        pair_id=pair_id,
        latency_seconds=latency,
        prompt_tokens=100,
        completion_tokens=50,
        cost_rub=0.001,
        actual_answer="ans",
        actual_citations=[],
        scores=EvalScores(
            answer_correctness=None,
            faithfulness=None,
            citation_accuracy=citation,
            refusal_correctness=None,
        ),
        composite=None,
        error=error,
    )


def test_aggregate_empty_returns_zeros() -> None:
    agg = aggregate_results([])
    assert agg.pair_count == 0
    assert agg.error_count == 0
    assert agg.latency_p50 == 0.0
    assert agg.composite_avg is None


def test_aggregate_counts_errors_separately() -> None:
    results = [
        _result("p1"),
        _result("p2", error="RuntimeError: x"),
        _result("p3"),
    ]
    agg = aggregate_results(results)
    assert agg.pair_count == 3
    assert agg.error_count == 1


def test_aggregate_latency_p50_p95_only_successful() -> None:
    """Errored pairs не входят в latency aggregation — они skewed бы дистрибуцию."""
    results = [
        _result("p1", latency=0.1),
        _result("p2", latency=0.2),
        _result("p3", latency=10.0, error="timeout"),  # ignored
    ]
    agg = aggregate_results(results)
    # p50 of [0.1, 0.2] = 0.15
    assert agg.latency_p50 == pytest.approx(0.15)
    # p95 of [0.1, 0.2] ≈ 0.195
    assert agg.latency_p95 > 0.1


def test_aggregate_composite_avg_is_none_when_no_composites() -> None:
    """MVP scenario — все per-pair composites = None → aggregate тоже None."""
    results = [_result("p1"), _result("p2")]
    agg = aggregate_results(results)
    assert agg.composite_avg is None


def test_aggregate_citation_avg_excludes_none() -> None:
    """Pair с citation=None (errored) не пушит avg вниз."""
    results = [
        _result("p1", citation=1.0),
        _result("p2", citation=0.5),
        _result("p3", citation=None, error="timeout"),  # excluded
    ]
    agg = aggregate_results(results)
    assert agg.citation_accuracy_avg == 0.75


def test_new_report_contains_run_id_and_timestamp() -> None:
    report = new_report(
        provider="mock",
        judge="mock",
        dataset_path=Path("tests/eval/golden.jsonl"),
        dataset_sha256="abc",
        per_pair=[_result("p1")],
    )
    assert len(report.run_id) > 0
    assert report.run_started_at.endswith("Z")
    assert report.provider == "mock"
    assert report.aggregate.pair_count == 1


def test_report_json_serialization_valid(tmp_path: Path) -> None:
    report = new_report(
        provider="mock",
        judge="mock",
        dataset_path=Path("dataset.jsonl"),
        dataset_sha256="abc",
        per_pair=[_result("p1"), _result("p2")],
    )
    out = tmp_path / "report.json"
    report.save(out)
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["provider"] == "mock"
    assert parsed["aggregate"]["pair_count"] == 2
    assert len(parsed["per_pair"]) == 2
    assert parsed["per_pair"][0]["pair_id"] == "p1"


def test_report_save_atomic_no_partial_file(tmp_path: Path) -> None:
    """После save должен оставаться только финальный файл, не .tmp."""
    report = new_report(
        provider="mock",
        judge="mock",
        dataset_path=Path("x.jsonl"),
        dataset_sha256="x",
        per_pair=[_result()],
    )
    out = tmp_path / "report.json"
    report.save(out)
    assert out.exists()
    assert not out.with_suffix(out.suffix + ".tmp").exists()
