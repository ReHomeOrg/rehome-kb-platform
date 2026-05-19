"""SecurityIncident ORM model (#231, OpenAPI §SecurityIncident).

ФЗ-152 §17.1 registry. Severity / status / detected_by enums mirror'ятся
в migration 0024 CHECK constraint — drift sync verifies (см.
`test_security_incidents_check_sync`).

Severity rules для `rkn_notification_required`:
- low / medium → False (внутренний log, без РКН).
- high / critical → True (24h факт / 72h полный состав РКН).

Status lifecycle:
  OPEN → INVESTIGATING → RESOLVED | FALSE_POSITIVE
  (resolved_at set ↔ terminal status; DB CHECK enforces).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base

SEVERITIES: Final[tuple[str, ...]] = ("low", "medium", "high", "critical")
STATUSES: Final[tuple[str, ...]] = ("OPEN", "INVESTIGATING", "RESOLVED", "FALSE_POSITIVE")
DETECTED_BY: Final[tuple[str, ...]] = (
    "monitoring",
    "audit",
    "user_report",
    "staff",
    "automated_scan",
)

# Terminal status — resolved_at обязан быть set.
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({"RESOLVED", "FALSE_POSITIVE"})

# Severity → ФЗ-152 РКН-уведомление gate.
# `high` / `critical` требуют notification per §17.1.
_REQUIRES_RKN: Final[frozenset[str]] = frozenset({"high", "critical"})


def requires_rkn_notification(severity: str) -> bool:
    """Helper для repo при insert'е: severity-driven default."""
    return severity in _REQUIRES_RKN


class SecurityIncident(Base):
    """Security incident registry row."""

    __tablename__ = "security_incidents"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    incident_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="OPEN")
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    detected_by: Mapped[str] = mapped_column(String(32), nullable=False)
    affected_resources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    rkn_notification_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    rkn_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    __table_args__ = (
        CheckConstraint(
            f"severity IN ({', '.join(repr(v) for v in SEVERITIES)})",
            name="ck_security_incidents_severity",
        ),
        CheckConstraint(
            f"status IN ({', '.join(repr(v) for v in STATUSES)})",
            name="ck_security_incidents_status",
        ),
        CheckConstraint(
            f"detected_by IN ({', '.join(repr(v) for v in DETECTED_BY)})",
            name="ck_security_incidents_detected_by",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SecurityIncident id={self.id} severity={self.severity} " f"status={self.status}>"


__all__ = [
    "DETECTED_BY",
    "SEVERITIES",
    "STATUSES",
    "SecurityIncident",
    "TERMINAL_STATUSES",
    "requires_rkn_notification",
]
