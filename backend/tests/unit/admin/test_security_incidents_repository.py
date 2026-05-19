"""Unit tests для SecurityIncidentRepository (#231).

State machine semantics + create defaults — без БД (mock session).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.api.admin.security_incidents_models import SecurityIncident
from src.api.admin.security_incidents_repository import (
    InvalidIncidentTransitionError,
    SecurityIncidentRepository,
)


def _make_incident(**over: object) -> SecurityIncident:
    inc = SecurityIncident()
    inc.id = uuid4()
    inc.incident_type = "access_violation"
    inc.severity = "medium"
    inc.status = "OPEN"
    inc.detected_at = datetime(2026, 5, 20, tzinfo=UTC)
    inc.detected_by = "audit"
    inc.affected_resources = []
    inc.rkn_notification_required = False
    inc.rkn_notified_at = None
    inc.resolution_note = None
    inc.resolved_at = None
    inc.created_at = datetime(2026, 5, 20, tzinfo=UTC)
    inc.updated_at = datetime(2026, 5, 20, tzinfo=UTC)
    for k, v in over.items():
        setattr(inc, k, v)
    return inc


def _session() -> MagicMock:
    s = MagicMock()
    s.add = MagicMock()
    s.flush = AsyncMock()
    s.execute = AsyncMock()
    return s


# ---------------------------------------------------------------------------
# create()


@pytest.mark.asyncio
async def test_create_low_severity_no_rkn() -> None:
    session = _session()
    repo = SecurityIncidentRepository(session)
    await repo.create(
        incident_type="access_violation",
        severity="low",
        detected_by="audit",
    )
    session.add.assert_called_once()
    inc = session.add.call_args.args[0]
    assert inc.severity == "low"
    assert inc.status == "OPEN"
    assert inc.rkn_notification_required is False


@pytest.mark.asyncio
async def test_create_critical_severity_requires_rkn() -> None:
    session = _session()
    repo = SecurityIncidentRepository(session)
    await repo.create(
        incident_type="suspected_data_leak",
        severity="critical",
        detected_by="monitoring",
    )
    inc = session.add.call_args.args[0]
    assert inc.severity == "critical"
    assert inc.rkn_notification_required is True


@pytest.mark.asyncio
async def test_create_with_affected_resources() -> None:
    session = _session()
    repo = SecurityIncidentRepository(session)
    affected = [{"type": "article", "id": "abc-123"}]
    await repo.create(
        incident_type="suspected_data_leak",
        severity="high",
        detected_by="user_report",
        affected_resources=affected,
    )
    inc = session.add.call_args.args[0]
    assert inc.affected_resources == affected
    assert inc.rkn_notification_required is True  # high → True


# ---------------------------------------------------------------------------
# update() — state machine


@pytest.mark.asyncio
async def test_update_transition_to_resolved_sets_resolved_at() -> None:
    inc = _make_incident(status="INVESTIGATING")
    session = _session()
    repo = SecurityIncidentRepository(session)
    await repo.update(inc, status="RESOLVED", resolution_note="false alarm")
    assert inc.status == "RESOLVED"
    assert inc.resolved_at is not None
    assert inc.resolution_note == "false alarm"


@pytest.mark.asyncio
async def test_update_transition_to_false_positive_sets_resolved_at() -> None:
    inc = _make_incident(status="OPEN")
    session = _session()
    repo = SecurityIncidentRepository(session)
    await repo.update(inc, status="FALSE_POSITIVE")
    assert inc.status == "FALSE_POSITIVE"
    assert inc.resolved_at is not None


@pytest.mark.asyncio
async def test_update_terminal_to_non_terminal_raises() -> None:
    """RESOLVED → OPEN не разрешён (compliance: incident reopen — new row)."""
    inc = _make_incident(
        status="RESOLVED",
        resolved_at=datetime(2026, 5, 19, tzinfo=UTC),
    )
    session = _session()
    repo = SecurityIncidentRepository(session)
    with pytest.raises(InvalidIncidentTransitionError):
        await repo.update(inc, status="OPEN")


@pytest.mark.asyncio
async def test_update_open_to_investigating_works() -> None:
    inc = _make_incident(status="OPEN")
    session = _session()
    repo = SecurityIncidentRepository(session)
    await repo.update(inc, status="INVESTIGATING")
    assert inc.status == "INVESTIGATING"
    assert inc.resolved_at is None


@pytest.mark.asyncio
async def test_update_only_resolution_note_no_status_change() -> None:
    inc = _make_incident(status="INVESTIGATING")
    session = _session()
    repo = SecurityIncidentRepository(session)
    await repo.update(inc, resolution_note="ongoing investigation")
    assert inc.status == "INVESTIGATING"
    assert inc.resolution_note == "ongoing investigation"
    assert inc.resolved_at is None


@pytest.mark.asyncio
async def test_update_rkn_notified_at_passthrough() -> None:
    inc = _make_incident(
        severity="high",
        rkn_notification_required=True,
        rkn_notified_at=None,
    )
    notified = datetime(2026, 5, 20, 12, tzinfo=UTC)
    session = _session()
    repo = SecurityIncidentRepository(session)
    await repo.update(inc, rkn_notified_at=notified)
    assert inc.rkn_notified_at == notified


@pytest.mark.asyncio
async def test_update_resolved_preserves_existing_resolved_at() -> None:
    """Идемпотентный repeated update RESOLVED → не перезатирает resolved_at."""
    fixed = datetime(2026, 5, 19, tzinfo=UTC)
    inc = _make_incident(status="RESOLVED", resolved_at=fixed)
    session = _session()
    repo = SecurityIncidentRepository(session)
    await repo.update(inc, status="RESOLVED")
    assert inc.resolved_at == fixed  # not overwritten


# ---------------------------------------------------------------------------
# list / get


@pytest.mark.asyncio
async def test_list_filter_severity_and_status_in_sql() -> None:
    session = _session()
    session.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: [])))
    repo = SecurityIncidentRepository(session)
    await repo.list_filtered(severity="critical", status="OPEN")
    stmt = session.execute.call_args.args[0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "severity" in compiled
    assert "status" in compiled


@pytest.mark.asyncio
async def test_get_by_id_returns_none_for_missing() -> None:
    session = _session()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    repo = SecurityIncidentRepository(session)
    result = await repo.get_by_id(uuid4())
    assert result is None
