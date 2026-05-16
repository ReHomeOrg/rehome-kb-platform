"""Unit tests для eval/dataset.py loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.eval.dataset import EvalPair, dataset_sha256, load_dataset


def _write_jsonl(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "eval.jsonl"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


VALID_PAIR = (
    '{"id":"a","category":"simple_faq","scope":"public_anonymous",'
    '"question":"q?","expected_answer":"a","expected_citations":["x"],"tags":[]}'
)


def test_load_dataset_valid_single_pair(tmp_path: Path) -> None:
    p = _write_jsonl(tmp_path, [VALID_PAIR])
    pairs = load_dataset(p)
    assert len(pairs) == 1
    assert pairs[0].id == "a"
    assert pairs[0].category == "simple_faq"
    assert pairs[0].expected_citations == ["x"]


def test_load_dataset_skips_blank_and_comment_lines(tmp_path: Path) -> None:
    other = VALID_PAIR.replace('"a"', '"b"', 1)
    p = _write_jsonl(tmp_path, ["", VALID_PAIR, "# comment", "  ", other])
    pairs = load_dataset(p)
    assert {p.id for p in pairs} == {"a", "b"}


def test_load_dataset_unknown_category_raises_with_line_context(
    tmp_path: Path,
) -> None:
    bad = (
        '{"id":"a","category":"unknown","scope":"public_anonymous",'
        '"question":"q","expected_answer":"a"}'
    )
    p = _write_jsonl(tmp_path, [VALID_PAIR, bad])
    with pytest.raises(ValueError, match="Line 2"):
        load_dataset(p)


def test_load_dataset_unknown_scope_raises(tmp_path: Path) -> None:
    bad = '{"id":"a","category":"simple_faq","scope":"hacker","question":"q","expected_answer":"a"}'
    p = _write_jsonl(tmp_path, [bad])
    with pytest.raises(ValueError, match="Line 1"):
        load_dataset(p)


def test_load_dataset_duplicate_id_raises(tmp_path: Path) -> None:
    p = _write_jsonl(tmp_path, [VALID_PAIR, VALID_PAIR])
    with pytest.raises(ValueError, match="дубликат id 'a'"):
        load_dataset(p)


def test_load_dataset_malformed_json_raises(tmp_path: Path) -> None:
    p = _write_jsonl(tmp_path, ["{not json"])
    with pytest.raises(ValueError, match="Line 1.*JSON"):
        load_dataset(p)


def test_load_dataset_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_dataset(Path("/tmp/does-not-exist.jsonl"))


def test_load_dataset_empty_file_raises(tmp_path: Path) -> None:
    p = _write_jsonl(tmp_path, [])
    with pytest.raises(ValueError, match="не содержит ни одной пары"):
        load_dataset(p)


def test_load_dataset_oversize_raises(tmp_path: Path) -> None:
    """Anti-DoS guard: 10MB лимит."""
    p = tmp_path / "huge.jsonl"
    # 11MB blank-comment file.
    p.write_text("# " + "x" * (11 * 1024 * 1024) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="anti-DoS"):
        load_dataset(p)


def test_eval_pair_frozen() -> None:
    pair = EvalPair(
        id="a",
        category="simple_faq",
        scope="public_anonymous",
        question="q",
        expected_answer="a",
    )
    with pytest.raises(ValidationError):
        pair.question = "mutate"


def test_dataset_sha256_changes_when_content_changes(tmp_path: Path) -> None:
    p1 = _write_jsonl(tmp_path, [VALID_PAIR])
    sha1 = dataset_sha256(p1)
    p1.write_text(VALID_PAIR + "\n" + VALID_PAIR.replace('"a"', '"b"', 1), encoding="utf-8")
    sha2 = dataset_sha256(p1)
    assert sha1 != sha2


def test_load_golden_dataset() -> None:
    """Реальный bootstrap dataset должен loadиться без ошибок."""
    golden = Path(__file__).resolve().parents[2] / "eval" / "golden.jsonl"
    pairs = load_dataset(golden)
    assert len(pairs) >= 10
    # Все категории, перечисленные в ТЗ §3.1, должны быть представлены
    # хотя бы по одной паре (sanity: bootstrap не пропускает важный bucket).
    categories = {p.category for p in pairs}
    assert categories >= {
        "simple_faq",
        "legal",
        "financial",
        "multi_step",
        "paraphrase",
        "dialog_context",
        "off_topic",
        "prompt_injection",
        "pii_third_party",
    }
