"""security_incidents — registry security событий (#231, OpenAPI §SecurityIncident)

Revision ID: 0024_security_incidents
Revises: 0024_merge_heads
Create Date: 2026-05-20 01:00:00.000000

ФЗ-152 §17.1: оператор персональных данных обязан фиксировать
incidents (попытки обхода прав / утечки / suspicious activity) с
notification РКН в 24h (факт) / 72h (полный состав).

Rows создаются автоматически:
- audit.security_event webhook emitter (см. #223) — попытки обхода
  scope, idempotency replay attempts. Wiring через
  `SecurityIncidentRepository.create` — backlog (#223 merges first).
- monitoring systems (external) — через admin-only POST endpoint
  (отсутствует в OpenAPI; добавится backlog'ом если нужно).

Admin CRUD endpoints (этот PR):
- GET /admin/security-incidents (list с filter'ами severity / status).
- GET /admin/security-incidents/{id} (detail).
- PATCH /admin/security-incidents/{id} (update status + resolution_note +
  rkn_notified_at).

ФЗ-152 fields:
- `rkn_notification_required` — set'ится по severity rules (см.
  builder). High/critical → True; low/medium → False (per ФЗ-152 §17.1
  threshold).
- `rkn_notified_at` — manual fill после уведомления РКН.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024_security_incidents"
down_revision: str | None = "0024_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SEVERITIES = ("low", "medium", "high", "critical")
_STATUSES = ("OPEN", "INVESTIGATING", "RESOLVED", "FALSE_POSITIVE")
_DETECTED_BY = ("monitoring", "audit", "user_report", "staff", "automated_scan")


def _quote_set(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        "security_incidents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("incident_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="OPEN"),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("detected_by", sa.String(length=32), nullable=False),
        sa.Column(
            "affected_resources",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "rkn_notification_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("rkn_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            f"severity IN ({_quote_set(_SEVERITIES)})",
            name="ck_security_incidents_severity",
        ),
        sa.CheckConstraint(
            f"status IN ({_quote_set(_STATUSES)})",
            name="ck_security_incidents_status",
        ),
        sa.CheckConstraint(
            f"detected_by IN ({_quote_set(_DETECTED_BY)})",
            name="ck_security_incidents_detected_by",
        ),
        sa.CheckConstraint(
            # Terminal status (RESOLVED / FALSE_POSITIVE) ↔ resolved_at set.
            "(resolved_at IS NULL AND status IN ('OPEN', 'INVESTIGATING')) "
            "OR (resolved_at IS NOT NULL AND status IN ('RESOLVED', 'FALSE_POSITIVE'))",
            name="ck_security_incidents_resolved_at_consistency",
        ),
    )
    # Keyset cursor pagination — (detected_at DESC, id DESC).
    op.create_index(
        "ix_security_incidents_detected_id",
        "security_incidents",
        [sa.text("detected_at DESC"), sa.text("id DESC")],
    )
    # Status / severity filters — typical admin list query.
    op.create_index(
        "ix_security_incidents_status",
        "security_incidents",
        ["status"],
        postgresql_where=sa.text("status IN ('OPEN', 'INVESTIGATING')"),
    )
    op.create_index(
        "ix_security_incidents_severity",
        "security_incidents",
        ["severity"],
        postgresql_where=sa.text("severity IN ('high', 'critical')"),
    )
    # РКН notification queue — высокий severity без notify timestamp.
    op.create_index(
        "ix_security_incidents_rkn_pending",
        "security_incidents",
        ["detected_at"],
        postgresql_where=sa.text(
            "rkn_notification_required = true AND rkn_notified_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_security_incidents_rkn_pending", table_name="security_incidents")
    op.drop_index("ix_security_incidents_severity", table_name="security_incidents")
    op.drop_index("ix_security_incidents_status", table_name="security_incidents")
    op.drop_index("ix_security_incidents_detected_id", table_name="security_incidents")
    op.drop_table("security_incidents")
