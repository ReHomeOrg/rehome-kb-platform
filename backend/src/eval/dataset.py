"""Eval dataset loader — JSONL формат, Pydantic schema (ADR-0013 §2).

Одна пара на строку:

    {
      "id": "faq-deposit-001",
      "category": "simple_faq",
      "scope": "public_anonymous",
      "question": "Сколько составляет залог?",
      "expected_answer": "Залога нет...",
      "expected_citations": ["article:rental-service-fee-policy"],
      "tags": ["finance", "onboarding"]
    }

Категории и scope'ы — fixed Literal'ы (anti-typo: malformed dataset →
ValidationError на load, не silent miscount в reports).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, Field

# Категории по ТЗ §3.1 — 9 фиксированных bucket'ов.
EvalCategory = Literal[
    "simple_faq",
    "legal",
    "financial",
    "multi_step",
    "paraphrase",
    "dialog_context",
    "off_topic",
    "prompt_injection",
    "pii_third_party",
]

# Scope'ы по ТЗ §2.2 — 7 разрешённых значений. Совпадает с
# auth/scope.py Scope enum (drift caught: см. test_eval_scope_sync.py
# (backlog)).
EvalScope = Literal[
    "public_anonymous",
    "public_tenant",
    "public_landlord",
    "public_agent",
    "staff_support",
    "staff_legal",
    "staff_admin",
]


class EvalPair(BaseModel):
    """Одна Q&A пара из эталонного набора.

    Pydantic validate'ит:
    - `id` непустой (id используется как dict key в reports).
    - `category` ∈ EvalCategory.
    - `scope` ∈ EvalScope.
    - `expected_citations` — массив строк, may быть пуст (off_topic
      категории, например).
    """

    id: str = Field(min_length=1, max_length=200)
    category: EvalCategory
    scope: EvalScope
    question: str = Field(min_length=1, max_length=2000)
    expected_answer: str = Field(min_length=1, max_length=10000)
    expected_citations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


_MAX_DATASET_SIZE_MB: Final = 10


def load_dataset(path: Path) -> list[EvalPair]:
    """Загрузить JSONL → list[EvalPair].

    Raises:
        FileNotFoundError: путь не существует.
        ValueError: пустой файл или dataset > 10 MB (anti-DoS на
          CI runners — реальный 200-pair dataset ~200KB, лимит щедрый).
        pydantic.ValidationError: невалидная пара (с line-numbered context'ом).
    """
    if not path.is_file():
        raise FileNotFoundError(f"Dataset не найден: {path}")
    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > _MAX_DATASET_SIZE_MB:
        raise ValueError(
            f"Dataset {path} превышает {_MAX_DATASET_SIZE_MB} MB "
            f"(got {size_mb:.1f} MB) — anti-DoS guard"
        )

    pairs: list[EvalPair] = []
    seen_ids: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Line {lineno}: невалидный JSON — {exc}") from exc
            try:
                pair = EvalPair.model_validate(obj)
            except Exception as exc:
                # ValidationError или другой — wrap с line context'ом.
                raise ValueError(f"Line {lineno}: {exc}") from exc
            if pair.id in seen_ids:
                raise ValueError(f"Line {lineno}: дубликат id '{pair.id}'")
            seen_ids.add(pair.id)
            pairs.append(pair)

    if not pairs:
        raise ValueError(f"Dataset {path} не содержит ни одной пары")
    return pairs


def dataset_sha256(path: Path) -> str:
    """Hex digest для report metadata — proof of dataset version.

    Любая правка dataset'а инвалидирует прошлые run'ы (нельзя сравнивать
    результаты разных версий по одному report'у). SHA256 — единственный
    обязательный header в JSON report'е.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(64 * 1024):
            h.update(chunk)
    return h.hexdigest()
