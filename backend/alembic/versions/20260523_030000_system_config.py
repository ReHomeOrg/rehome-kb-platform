"""system_config — writable runtime config storage (#264, ADR-0019)

Revision ID: 0024_system_config
Revises: 0024_admin_tasks
Create Date: 2026-05-23 03:00:00.000000

Single-row JSONB table per ADR-0019 Вариант A:
- `id=1` constraint (только одна row).
- `data` JSONB — overlay поверх env-config (allow-listed keys).
- `updated_at` / `updated_by` — audit metadata.

Initial INSERT: id=1, data={}, updated_by='system_init'.

Settings layer (см. `src/api/admin/system_config_overlay.py`) reads
env как primary + overlay'ит allow-listed keys из `data` для read
endpoints. PATCH endpoint обновляет `data`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024_system_config"
down_revision: str | None = "0024_admin_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("updated_by", sa.Text(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_system_config_single_row"),
    )
    # Seed the row.
    op.execute(
        "INSERT INTO system_config (id, data, updated_by) " "VALUES (1, '{}'::jsonb, 'system_init')"
    )


def downgrade() -> None:
    op.drop_table("system_config")
