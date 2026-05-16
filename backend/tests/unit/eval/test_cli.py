"""Unit tests для eval/cli.py — full pipeline через MockProvider + MockJudge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.chat.llm.mock import MockProvider
from src.eval.cli import _parse_args, build_judge, build_provider, main
from src.eval.judge import MockJudge

# ---------------------------------------------------------------------------
# Argument parsing


def test_parse_args_all_required() -> None:
    args = _parse_args(
        [
            "--provider",
            "mock",
            "--judge",
            "mock",
            "--dataset",
            "ds.jsonl",
            "--out",
            "r.json",
        ]
    )
    assert args.provider == "mock"
    assert args.judge == "mock"
    assert args.dataset == Path("ds.jsonl")
    assert args.out == Path("r.json")


def test_parse_args_missing_required_raises_systemexit() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--provider", "mock"])


def test_parse_args_invalid_provider_choice() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--provider", "unknown", "--judge", "mock", "--dataset", "x", "--out", "y"])


# ---------------------------------------------------------------------------
# Factory functions


def test_build_provider_mock() -> None:
    provider = build_provider("mock")
    assert isinstance(provider, MockProvider)


def test_build_provider_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Неизвестный provider"):
        build_provider("not_real")


def test_build_judge_mock() -> None:
    judge = build_judge("mock")
    assert isinstance(judge, MockJudge)


def test_build_judge_llm_raises_not_implemented() -> None:
    """LLMJudge raise'ит в конструкторе — propagate'ится наверх."""
    with pytest.raises(NotImplementedError, match="ADR-0013"):
        build_judge("llm")


# ---------------------------------------------------------------------------
# Full pipeline e2e — MockProvider + MockJudge + 3-pair dataset


def _write_mini_dataset(tmp_path: Path) -> Path:
    pairs = [
        {
            "id": "q1",
            "category": "simple_faq",
            "scope": "public_anonymous",
            "question": "Сколько составляет залог?",
            "expected_answer": "Залога нет",
            "expected_citations": ["article:rental-service-fee-policy"],
        },
        {
            "id": "q2",
            "category": "off_topic",
            "scope": "public_anonymous",
            "question": "Какая погода?",
            "expected_answer": "Я не могу ответить на этот вопрос",
            "expected_citations": [],
        },
        {
            "id": "q3",
            "category": "simple_faq",
            "scope": "public_anonymous",
            "question": "Что такое сервисный платёж?",
            "expected_answer": "Невозвратный платёж при заезде",
            "expected_citations": ["article:rental-service-fee-policy"],
        },
    ]
    ds = tmp_path / "mini.jsonl"
    ds.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in pairs))
    return ds


def test_cli_main_full_pipeline_writes_report(tmp_path: Path) -> None:
    """End-to-end: argparse → load dataset → MockProvider + MockJudge → JSON report."""
    dataset = _write_mini_dataset(tmp_path)
    out = tmp_path / "report.json"
    exit_code = main(
        [
            "--provider",
            "mock",
            "--judge",
            "mock",
            "--dataset",
            str(dataset),
            "--out",
            str(out),
        ]
    )
    assert exit_code == 0
    assert out.exists()
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["provider"] == "mock"
    assert report["judge"] == "mock"
    assert report["aggregate"]["pair_count"] == 3
    assert report["aggregate"]["error_count"] == 0
    assert len(report["per_pair"]) == 3
    # Citation_accuracy для MockProvider (echo) с пустыми citations → 0
    # для пар с expected_citations и 1.0 для пар без них.
    assert report["aggregate"]["citation_accuracy_avg"] >= 0.0
    # Composite в MVP всегда None (faithfulness/refusal не у всех заполняется).
    assert report["aggregate"]["composite_avg"] is None


def test_cli_main_nonexistent_dataset_returns_1(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    exit_code = main(
        [
            "--provider",
            "mock",
            "--judge",
            "mock",
            "--dataset",
            str(tmp_path / "missing.jsonl"),
            "--out",
            str(out),
        ]
    )
    assert exit_code == 1
    assert not out.exists()


def test_cli_main_llm_judge_returns_2(tmp_path: Path) -> None:
    """LLMJudge backlog → exit code 2 (provider/judge construction error)."""
    dataset = _write_mini_dataset(tmp_path)
    out = tmp_path / "report.json"
    exit_code = main(
        [
            "--provider",
            "mock",
            "--judge",
            "llm",
            "--dataset",
            str(dataset),
            "--out",
            str(out),
        ]
    )
    assert exit_code == 2
    assert not out.exists()
