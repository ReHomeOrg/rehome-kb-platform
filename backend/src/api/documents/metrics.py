"""Prometheus metrics для documents upload/download (ADR-0012).

Pull-model: метрики экспортируются через общий `/metrics` endpoint
(см. `src/api/observability/metrics.py`).

Metrics:
- `kb_documents_files_uploaded_total{format, outcome}` — counter
  попыток upload.
- `kb_documents_files_downloaded_total{format, outcome}` — counter
  попыток generation signed URL.

Outcomes (общий enum, не все применимы к обоим endpoint'ам):
- `success` — 201/302 happy path.
- `not_found` — 404 mask (нет доступа / нет документа / нет файла).
- `oversized` — 413 (только upload).
- `storage_unavailable` — 503 (MinIO not configured / transient 5xx).
- `storage_error` — 502 (MinIO 5xx non-transient).

Cardinality: format ∈ {docx, pdf, html} × outcome ∈ 5 = 15 series
на counter. Итого 30 series — далеко от cardinality-bomb.
"""

from typing import Final

from prometheus_client import Counter

DOWNLOADED_TOTAL: Final = Counter(
    "kb_documents_files_downloaded_total",
    "Total document file download attempts grouped by format and outcome.",
    labelnames=("format", "outcome"),
)

UPLOADED_TOTAL: Final = Counter(
    "kb_documents_files_uploaded_total",
    "Total document file upload attempts grouped by format and outcome.",
    labelnames=("format", "outcome"),
)


# Outcome string constants — anti-typo guard. Используются как
# argument'ы `.labels(outcome=...)` и в test assertions.
OUTCOME_SUCCESS: Final = "success"
OUTCOME_NOT_FOUND: Final = "not_found"
OUTCOME_OVERSIZED: Final = "oversized"
OUTCOME_STORAGE_UNAVAILABLE: Final = "storage_unavailable"
OUTCOME_STORAGE_ERROR: Final = "storage_error"


__all__ = [
    "DOWNLOADED_TOTAL",
    "OUTCOME_NOT_FOUND",
    "OUTCOME_OVERSIZED",
    "OUTCOME_STORAGE_ERROR",
    "OUTCOME_STORAGE_UNAVAILABLE",
    "OUTCOME_SUCCESS",
    "UPLOADED_TOTAL",
]
