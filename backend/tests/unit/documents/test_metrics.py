"""Unit tests для documents Prometheus metrics (#174)."""

from __future__ import annotations

from src.api.documents.metrics import (
    DOWNLOADED_TOTAL,
    OUTCOME_NOT_FOUND,
    OUTCOME_OVERSIZED,
    OUTCOME_STORAGE_ERROR,
    OUTCOME_STORAGE_UNAVAILABLE,
    OUTCOME_SUCCESS,
    UPLOADED_TOTAL,
)


def _value(counter: object, **labels: str) -> float:
    """Read counter value через `._value.get()` API."""
    metric = counter.labels(**labels)  # type: ignore[attr-defined]
    return float(metric._value.get())


def test_outcomes_are_distinct_string_constants() -> None:
    """Anti-typo guard — каждый OUTCOME_* должен быть уникальной строкой."""
    values = {
        OUTCOME_SUCCESS,
        OUTCOME_NOT_FOUND,
        OUTCOME_OVERSIZED,
        OUTCOME_STORAGE_UNAVAILABLE,
        OUTCOME_STORAGE_ERROR,
    }
    assert len(values) == 5, "OUTCOME_* constants должны быть уникальны"
    for v in values:
        assert isinstance(v, str)
        assert v == v.lower()  # snake_case


def test_downloaded_counter_increments_on_success() -> None:
    before = _value(DOWNLOADED_TOTAL, format="pdf", outcome=OUTCOME_SUCCESS)
    DOWNLOADED_TOTAL.labels(format="pdf", outcome=OUTCOME_SUCCESS).inc()
    after = _value(DOWNLOADED_TOTAL, format="pdf", outcome=OUTCOME_SUCCESS)
    assert after == before + 1.0


def test_uploaded_counter_increments_on_oversized() -> None:
    before = _value(UPLOADED_TOTAL, format="docx", outcome=OUTCOME_OVERSIZED)
    UPLOADED_TOTAL.labels(format="docx", outcome=OUTCOME_OVERSIZED).inc()
    after = _value(UPLOADED_TOTAL, format="docx", outcome=OUTCOME_OVERSIZED)
    assert after == before + 1.0


def test_counters_have_format_label_cardinality_bounded() -> None:
    """Cardinality guard: documents format ∈ {docx, pdf, html} × outcomes ∈ 5.

    Если кто-то добавит `format='exe'` в Counter labels — это backdoor
    cardinality growth. Проверяем что Counter принимает только known
    formats без падения, но invariant — формат validated на router level.
    """
    # Это smoke check, не enforcement. Реальный gate — router'овский
    # Literal["docx","pdf","html"] (FastAPI 422 на bad path param).
    DOWNLOADED_TOTAL.labels(format="pdf", outcome=OUTCOME_NOT_FOUND).inc(0)
    DOWNLOADED_TOTAL.labels(format="docx", outcome=OUTCOME_STORAGE_ERROR).inc(0)
    DOWNLOADED_TOTAL.labels(format="html", outcome=OUTCOME_SUCCESS).inc(0)
    # Если эти .labels(...) сработали без exception — Counter
    # сконфигурирован правильно.
