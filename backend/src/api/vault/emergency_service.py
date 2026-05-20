"""Emergency unlock orchestration (ADR-0021 A).

Per Architect approve note 2026-05-21:
- Severity per reason_category:
  * incident, forensic_audit → high
  * legal_order → medium
  * employee_departure, password_lost → low
- РКН notification ТОЛЬКО для reason_category=incident (это реальный
  breach §17.1). Severity-derived default из SecurityIncidentRepository
  overridden — explicit policy here.
- Auto-create security_incident на каждое emergency unlock event.

Service orchestrates три атомарных action'а:
  1. Create SecurityIncident (severity + RKN flag derived from reason).
  2. Create VaultEmergencyUnlockLog row (FK на incident).
  3. Record audit row.
Caller (router) owns commit + retrieves encrypted vault payload separately.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from src.api.admin.security_incidents_models import SecurityIncident
from src.api.audit.actions import (
    ACTION_VAULT_EMERGENCY_UNLOCK,
    RESOURCE_VAULT_USER,
)
from src.api.audit.repository import AuditRepository
from src.api.vault.emergency_repository import VaultEmergencyRepository
from src.api.vault.models import EMERGENCY_REASON_CATEGORIES, VaultEmergencyUnlockLog

# Mapping reason_category → SecurityIncident.severity (Architect 2026-05-21).
_SEVERITY_BY_REASON: Final[dict[str, str]] = {
    "incident": "high",
    "forensic_audit": "high",
    "legal_order": "medium",
    "employee_departure": "low",
    "password_lost": "low",
}

# RKN notification policy (Architect 2026-05-21): только incident.
_RKN_REQUIRED_REASONS: Final[frozenset[str]] = frozenset({"incident"})


def severity_for_reason(reason_category: str) -> str:
    """Return severity (low/medium/high/critical) для security_incident."""
    if reason_category not in EMERGENCY_REASON_CATEGORIES:
        raise ValueError(f"Unknown reason_category: {reason_category!r}")
    return _SEVERITY_BY_REASON[reason_category]


def rkn_required_for_reason(reason_category: str) -> bool:
    """Return True если reason мандатно требует РКН notify (только incident)."""
    return reason_category in _RKN_REQUIRED_REASONS


async def record_emergency_unlock(
    *,
    target_user_id: UUID,
    requested_by: str,
    reason_category: str,
    reason_text: str,
    emergency_repo: VaultEmergencyRepository,
    audit_repo: AuditRepository,
    session: object,
) -> VaultEmergencyUnlockLog:
    """Atomic orchestration: incident + unlock log + audit row.

    `session` parameter typed as object для loose coupling (caller передаёт
    AsyncSession). Все три write happen в caller's transaction; caller
    commit'ит.

    Returns the unlock log row (с populated security_incident_id).
    """
    if reason_category not in EMERGENCY_REASON_CATEGORIES:
        raise ValueError(
            f"Invalid reason_category: {reason_category!r}. "
            f"Allowed: {EMERGENCY_REASON_CATEGORIES}"
        )
    severity = severity_for_reason(reason_category)
    rkn_required = rkn_required_for_reason(reason_category)

    # Create SecurityIncident manually (не через repo.create) чтобы explicit
    # control над rkn_notification_required (Architect policy != severity-
    # derived default).
    incident = SecurityIncident(
        incident_type="emergency_access",
        severity=severity,
        status="OPEN",
        detected_by="emergency_unlock_endpoint",
        affected_resources=[
            {"type": "vault_user", "id": str(target_user_id)},
        ],
        rkn_notification_required=rkn_required,
    )
    session.add(incident)  # type: ignore[attr-defined]
    await session.flush()  # type: ignore[attr-defined]

    log_row = await emergency_repo.log(
        user_id=target_user_id,
        requested_by=requested_by,
        reason_category=reason_category,
        reason_text=reason_text,
        security_incident_id=incident.id,
        rkn_notify_required=rkn_required,
    )

    await audit_repo.record(
        actor_sub=requested_by,
        action=ACTION_VAULT_EMERGENCY_UNLOCK,
        resource_type=RESOURCE_VAULT_USER,
        resource_id=str(target_user_id),
        metadata={
            "reason_category": reason_category,
            "severity": severity,
            "rkn_notify_required": rkn_required,
            "security_incident_id": str(incident.id),
            "unlock_log_id": str(log_row.id),
        },
    )
    return log_row


__all__ = [
    "record_emergency_unlock",
    "rkn_required_for_reason",
    "severity_for_reason",
]
