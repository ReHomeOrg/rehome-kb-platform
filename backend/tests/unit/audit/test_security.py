"""Unit tests для security event helper (#223, ТЗ §5.1)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.audit.security import (
    SecurityEventType,
    SecuritySeverity,
    report_security_event,
)
from src.api.webhooks.dispatcher import WebhookEventDispatcher


def _dispatcher() -> tuple[MagicMock, AsyncMock]:
    fake = MagicMock(spec=WebhookEventDispatcher)
    fake.dispatch = AsyncMock(return_value=1)
    return fake, fake.dispatch


@pytest.mark.asyncio
async def test_report_security_event_dispatches_audit_security_event() -> None:
    """Helper передаёт event_type/severity/details в `audit.security_event`."""
    dispatcher, dispatch = _dispatcher()
    await report_security_event(
        dispatcher,
        event_type=SecurityEventType.AUTH_TARGET_BYPASS,
        severity=SecuritySeverity.WARNING,
        details={"slug": "x", "actor_sub": "u"},
    )
    dispatch.assert_awaited_once()
    kwargs = dispatch.call_args.kwargs
    assert kwargs["event_type"] == "audit.security_event"
    assert kwargs["payload"] == {
        "event_type": "auth.target_bypass",
        "severity": "warning",
        "details": {"slug": "x", "actor_sub": "u"},
    }


@pytest.mark.asyncio
async def test_report_security_event_swallows_dispatch_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Webhook dispatch failure не должен поднимать exception в caller."""
    import logging

    dispatcher, dispatch = _dispatcher()
    dispatch.side_effect = RuntimeError("broker down")
    caplog.set_level(logging.ERROR)

    # Should NOT raise.
    await report_security_event(
        dispatcher,
        event_type=SecurityEventType.IDEMPOTENCY_BODY_MISMATCH,
        severity=SecuritySeverity.WARNING,
        details={"key": "abc"},
    )
    # Log с экстра contextual fields.
    failure_records = [r for r in caplog.records if r.message == "security_event.dispatch_failed"]
    assert len(failure_records) == 1


def test_security_event_type_values_match_taxonomy() -> None:
    """Enum strings — stable contract для subscriber'ов."""
    assert SecurityEventType.AUTH_TARGET_BYPASS.value == "auth.target_bypass"
    assert SecurityEventType.IDEMPOTENCY_BODY_MISMATCH.value == "idempotency.body_mismatch"


def test_security_severity_values_match_taxonomy() -> None:
    assert SecuritySeverity.INFO.value == "info"
    assert SecuritySeverity.WARNING.value == "warning"
    assert SecuritySeverity.CRITICAL.value == "critical"
