"""audit_log composite index for keyset pagination (#343, follow-up)

Revision ID: 0028_audit_log_keyset_index
Revises: 0027_vault_emergency_access
Create Date: 2026-05-26 01:00:00.000000

Composite index `ix_audit_log_created_at_id_desc` на `(created_at DESC,
id DESC)` — поддерживает stable keyset cursor для `GET /admin/audit-log`
(`AuditRepository.list_records_keyset`).

До этого индекса keyset запросы фолбэчили на `ix_audit_log_actor_created`
/ `ix_audit_log_resource_created` (lead column не совпадает с keyset
sort), и при отсутствии фильтров — на seq scan. Composite covers
unfiltered keyset path; per-actor / per-resource keyset запросы по-
прежнему обслуживаются существующими indices (efficient prefix match).

Index size — small (audit log low-volume per row, 3 fields). Write
overhead acceptable: audit_log append-only, INSERT-only workload.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028_audit_log_keyset_index"
down_revision: str | None = "0027_vault_emergency_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_audit_log_created_at_id_desc " "ON audit_log (created_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at_id_desc", table_name="audit_log")
