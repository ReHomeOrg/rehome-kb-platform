"""collaborators portal_access + onboarding_source (ADR-0015, Slice 3)

Revision ID: 0020_collaborators_portal_access
Revises: 0019_collaborators_foundation
Create Date: 2026-05-17 01:00:00.000000

Расширяет `collaborators` table 3 колонками для Slice 3 (ТЗ §10.8):
- `portal_access_level` (NONE/LIGHT/FULL) — выбор коллаборанта при
  онбординге. Default NONE для existing rows (Slice 1+2 коллаборанты
  созданы до этой миграции — все pre-existing → NONE).
- `portal_access_history` (JSONB array) — audit trail смен tier'а.
  Pattern из documents.audit_log.
- `onboarding_source` (form/staff_invite/api/migration) — как
  коллаборант появился в системе. Default `staff_invite` для existing
  rows.

CHECK constraints на enum значения — drift тест test_collaborators_check_sync
verify'ит соответствие с access.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_collaborators_portal_access"
down_revision: str | None = "0019_collaborators_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PORTAL_ACCESS_LEVELS = ("NONE", "LIGHT", "FULL")
_ONBOARDING_SOURCES = ("form", "staff_invite", "api", "migration")


def upgrade() -> None:
    # portal_access_level — default NONE per ТЗ §10.8 (D-группа auto-NONE,
    # остальные — minimum tier до явного апгрейда).
    op.add_column(
        "collaborators",
        sa.Column(
            "portal_access_level",
            sa.String(length=10),
            nullable=False,
            server_default="NONE",
        ),
    )
    op.create_check_constraint(
        "ck_collaborators_portal_access_level",
        "collaborators",
        f"portal_access_level IN ({','.join(repr(v) for v in _PORTAL_ACCESS_LEVELS)})",
    )

    # portal_access_history — JSONB array с entries {from, to, by, ts, reason}.
    op.add_column(
        "collaborators",
        sa.Column(
            "portal_access_history",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # onboarding_source — default staff_invite для existing rows (они созданы
    # через POST /collaborators staff'ом, Slice 1+2).
    op.add_column(
        "collaborators",
        sa.Column(
            "onboarding_source",
            sa.String(length=20),
            nullable=False,
            server_default="staff_invite",
        ),
    )
    op.create_check_constraint(
        "ck_collaborators_onboarding_source",
        "collaborators",
        f"onboarding_source IN ({','.join(repr(v) for v in _ONBOARDING_SOURCES)})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_collaborators_onboarding_source", "collaborators")
    op.drop_column("collaborators", "onboarding_source")
    op.drop_column("collaborators", "portal_access_history")
    op.drop_constraint("ck_collaborators_portal_access_level", "collaborators")
    op.drop_column("collaborators", "portal_access_level")
