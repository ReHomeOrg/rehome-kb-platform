"""Smoke test: popular_query worker metrics registered."""

from prometheus_client import REGISTRY

from src.workers.popular_query.metrics import (
    DISPATCH_TOTAL,
    QUERIES_EMITTED,
    SCAN_DURATION_SECONDS,
    SCAN_ERRORS_TOTAL,
    SCAN_TOTAL,
)


def test_metrics_registered() -> None:
    """Метрики добавлены в default Registry — `start_http_server` их exposes."""
    names = {m.name for m in REGISTRY.collect()}
    assert "kb_popular_query_scan" in names
    assert "kb_popular_query_scan_errors" in names
    assert "kb_popular_query_dispatch" in names
    assert "kb_popular_query_queries_emitted" in names
    assert "kb_popular_query_scan_duration_seconds" in names


def test_metric_descriptions_nonempty() -> None:
    """Помогает поймать typo'и при копировании из соседних workers."""
    for m in (
        SCAN_TOTAL,
        SCAN_ERRORS_TOTAL,
        DISPATCH_TOTAL,
        QUERIES_EMITTED,
        SCAN_DURATION_SECONDS,
    ):
        # `_documentation` атрибут — public part Counter/Histogram spec.
        assert m._documentation
