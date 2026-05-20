"""Unit tests для emergency_service (ADR-0021 A)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.vault.emergency_service import (
    record_emergency_unlock,
    rkn_required_for_reason,
    severity_for_reason,
)
from src.api.vault.models import VaultEmergencyUnlockLog

# ---------------------------------------------------------------------------
# Severity + RKN mapping per Architect approve note 2026-05-21


def test_severity_incident_high() -> None:
    assert severity_for_reason("incident") == "high"


def test_severity_forensic_audit_high() -> None:
    assert severity_for_reason("forensic_audit") == "high"


def test_severity_legal_order_medium() -> None:
    assert severity_for_reason("legal_order") == "medium"


def test_severity_employee_departure_low() -> None:
    assert severity_for_reason("employee_departure") == "low"


def test_severity_password_lost_low() -> None:
    assert severity_for_reason("password_lost") == "low"


def test_severity_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown reason_category"):
        severity_for_reason("bogus")


def test_rkn_required_only_for_incident() -> None:
    assert rkn_required_for_reason("incident") is True
    for r in ("legal_order", "employee_departure", "forensic_audit", "password_lost"):
        assert rkn_required_for_reason(r) is False


# ---------------------------------------------------------------------------
# record_emergency_unlock orchestration


def _make_log_row(security_incident_id: Any = None) -> VaultEmergencyUnlockLog:
    row = VaultEmergencyUnlockLog()
    row.id = uuid4()
    row.security_incident_id = security_incident_id or uuid4()
    return row


@pytest.mark.asyncio
async def test_record_emergency_unlock_creates_incident_and_log() -> None:
    target_user = uuid4()
    emergency_repo = MagicMock()
    emergency_repo.log = AsyncMock(return_value=_make_log_row())
    audit_repo = MagicMock()
    audit_repo.record = AsyncMock()
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    await record_emergency_unlock(
        target_user_id=target_user,
        requested_by="admin-uuid",
        reason_category="incident",
        reason_text="suspected breach 2026-05-21",
        emergency_repo=emergency_repo,
        audit_repo=audit_repo,
        session=session,
    )

    # SecurityIncident создан через session.add.
    session.add.assert_called_once()
    incident = session.add.call_args.args[0]
    assert incident.incident_type == "emergency_access"
    assert incident.severity == "high"
    assert incident.rkn_notification_required is True
    assert incident.affected_resources == [{"type": "vault_user", "id": str(target_user)}]

    # Log row создан.
    emergency_repo.log.assert_awaited_once()
    log_kwargs = emergency_repo.log.call_args.kwargs
    assert log_kwargs["user_id"] == target_user
    assert log_kwargs["reason_category"] == "incident"
    assert log_kwargs["rkn_notify_required"] is True

    # Audit recorded.
    audit_repo.record.assert_awaited_once()
    ak = audit_repo.record.call_args.kwargs
    assert ak["action"] == "vault.emergency.unlock"
    assert ak["actor_sub"] == "admin-uuid"
    assert ak["metadata"]["reason_category"] == "incident"
    assert ak["metadata"]["severity"] == "high"
    assert ak["metadata"]["rkn_notify_required"] is True


@pytest.mark.asyncio
async def test_record_emergency_unlock_legal_order_no_rkn() -> None:
    """legal_order — medium severity, BUT rkn_notify_required=False (Architect)."""
    emergency_repo = MagicMock()
    emergency_repo.log = AsyncMock(return_value=_make_log_row())
    audit_repo = MagicMock()
    audit_repo.record = AsyncMock()
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    await record_emergency_unlock(
        target_user_id=uuid4(),
        requested_by="admin",
        reason_category="legal_order",
        reason_text="суд решение №123 от 2026-05-21",
        emergency_repo=emergency_repo,
        audit_repo=audit_repo,
        session=session,
    )

    incident = session.add.call_args.args[0]
    assert incident.severity == "medium"
    # Critical: legal_order NOT auto-notified to РКН (NDA risk).
    assert incident.rkn_notification_required is False
    assert emergency_repo.log.call_args.kwargs["rkn_notify_required"] is False


@pytest.mark.asyncio
async def test_record_emergency_unlock_employee_departure_low_severity() -> None:
    emergency_repo = MagicMock()
    emergency_repo.log = AsyncMock(return_value=_make_log_row())
    audit_repo = MagicMock()
    audit_repo.record = AsyncMock()
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    await record_emergency_unlock(
        target_user_id=uuid4(),
        requested_by="admin",
        reason_category="employee_departure",
        reason_text="Sarah уволилась 2026-05-15, надо банковский кабинет",
        emergency_repo=emergency_repo,
        audit_repo=audit_repo,
        session=session,
    )
    incident = session.add.call_args.args[0]
    assert incident.severity == "low"
    assert incident.rkn_notification_required is False


@pytest.mark.asyncio
async def test_record_emergency_unlock_rejects_invalid_reason() -> None:
    emergency_repo = MagicMock()
    audit_repo = MagicMock()
    session = MagicMock()

    with pytest.raises(ValueError, match="Invalid reason_category"):
        await record_emergency_unlock(
            target_user_id=uuid4(),
            requested_by="admin",
            reason_category="hacker",
            reason_text="x" * 20,
            emergency_repo=emergency_repo,
            audit_repo=audit_repo,
            session=session,
        )
