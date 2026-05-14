"""hr_employees foundation (#150, PZ §7).

Revision ID: 0017_hr_foundation
Revises: 0016_vault_foundation
Create Date: 2026-05-14 03:00:00.000000

Foundation table для kb-hr модуля (PZ §7). Карточка сотрудника +
employment lifecycle (HIRED → ACTIVE → ON_LEAVE → TERMINATED).

PII fields (ФИО, паспорт, ИНН, СНИЛС, банковские реквизиты) хранятся
здесь в зашифрованной форме (column-level encryption — backlog) либо
ссылками на kb-vault. В Stage 1 — minimal viable: ФИО, должность,
контакты как JSONB.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_hr_foundation"
down_revision: str | None = "0016_vault_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_employees",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # user_id — link к Keycloak user (optional: некоторые сотрудники
        # могут не иметь kb-platform аккаунта).
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True, unique=True),
        # Personnel number — внутренний код для приказов / ведомостей.
        sa.Column("personnel_number", sa.String(32), nullable=True, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("position", sa.String(200), nullable=False),
        sa.Column("department", sa.String(200), nullable=True),
        sa.Column("hire_date", sa.Date(), nullable=False),
        sa.Column("termination_date", sa.Date(), nullable=True),
        # ACTIVE / ON_LEAVE / TERMINATED — explicit enum через CHECK.
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        # Contacts JSONB — email, phone, emergency contact (нерегулируемые
        # PII; passport / СНИЛС / банк реквизиты — Stage 2 с encryption).
        sa.Column(
            "contact_info",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Notes — internal HR comments, performance reviews. Опционально.
        sa.Column(
            "notes",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ON_LEAVE', 'TERMINATED')",
            name="ck_hr_employees_status",
        ),
        # Terminated → termination_date обязателен.
        sa.CheckConstraint(
            "(status != 'TERMINATED') OR (termination_date IS NOT NULL)",
            name="ck_hr_employees_termination_date_required",
        ),
    )
    op.create_index("ix_hr_employees_status", "hr_employees", ["status"])
    op.create_index("ix_hr_employees_department", "hr_employees", ["department"])
    op.create_index("ix_hr_employees_full_name", "hr_employees", ["full_name"])


def downgrade() -> None:
    op.drop_index("ix_hr_employees_full_name", table_name="hr_employees")
    op.drop_index("ix_hr_employees_department", table_name="hr_employees")
    op.drop_index("ix_hr_employees_status", table_name="hr_employees")
    op.drop_table("hr_employees")
