"""personal_data_requests — ФЗ-152 §15 SAR (#232)

Revision ID: 0024_personal_data_requests
Revises: 0024_post_hr_pii_merge
Create Date: 2026-05-21 01:00:00.000000

Реестр заявок субъектов ПДн на provide / correct / delete / transfer
своих данных. ФЗ-152 §15 — оператор обязан ответить в 30 дней
(`due_at = created_at + 30 days`).

Rows создаются автоматически:
- User-facing form на rehome.one (subject submits request).
- Admin manually на behalf пользователя (rare — incoming letter / phone).
NO POST endpoint per OpenAPI — incoming flow handled внешними системами;
этот PR landит admin CRUD (GET list / GET one / PATCH).

`OVERDUE` status — auto-set background worker'ом (cron сравнивает
`due_at` < now() AND status IN ('NEW', 'IN_PROGRESS')). Worker — backlog.
MVP только manual `IN_PROGRESS` / `COMPLETED` / `REJECTED` через PATCH.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024_personal_data_requests"
down_revision: str | None = "0024_post_hr_pii_merge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TYPES = ("provide", "correct", "delete", "transfer")
_STATUSES = ("NEW", "IN_PROGRESS", "COMPLETED", "REJECTED", "OVERDUE")


def _quote_set(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        "personal_data_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="NEW"),
        # subject_id — Keycloak UUID; не FK (KB не владеет users — auth
        # identity opaque). Indexed для admin lookup'а «все заявки от user X».
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_email", sa.String(length=255), nullable=True),
        sa.Column("subject_phone", sa.String(length=32), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        # assigned_to — kb_user.id (staff responsible); FK не ставим
        # (kb_users — отдельный модуль; soft ref).
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        # due_at — created_at + 30 days (ФЗ-152 §15). Set'ится приложением
        # при insert (default expression on PostgreSQL поддерживает
        # interval, но safer хранить как `NOT NULL` + insert layer fills).
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "attachments",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("ARRAY[]::uuid[]"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            f"type IN ({_quote_set(_TYPES)})",
            name="ck_pd_requests_type",
        ),
        sa.CheckConstraint(
            f"status IN ({_quote_set(_STATUSES)})",
            name="ck_pd_requests_status",
        ),
        sa.CheckConstraint(
            # Terminal status (COMPLETED / REJECTED) ↔ completed_at set.
            # OVERDUE — terminal только когда due_at passed; не обязан
            # set'ить completed_at (это auto-status). Поэтому исключаем
            # OVERDUE из invariant'а.
            "(completed_at IS NULL AND status IN ('NEW', 'IN_PROGRESS', 'OVERDUE')) "
            "OR (completed_at IS NOT NULL AND status IN ('COMPLETED', 'REJECTED'))",
            name="ck_pd_requests_completed_at_consistency",
        ),
    )
    # Keyset cursor pagination — (created_at DESC, id DESC).
    op.create_index(
        "ix_pd_requests_created_id",
        "personal_data_requests",
        [sa.text("created_at DESC"), sa.text("id DESC")],
    )
    # Active queue — admin daily view.
    op.create_index(
        "ix_pd_requests_active",
        "personal_data_requests",
        ["due_at"],
        postgresql_where=sa.text("status IN ('NEW', 'IN_PROGRESS')"),
    )
    # OVERDUE candidate scan — background worker (backlog) cron'ает
    # этот index чтобы efficient'но найти заявки с прошедшим due_at.
    op.create_index(
        "ix_pd_requests_overdue_candidates",
        "personal_data_requests",
        ["due_at"],
        postgresql_where=sa.text("status IN ('NEW', 'IN_PROGRESS')"),
    )
    # Admin lookup «все заявки от user X».
    op.create_index(
        "ix_pd_requests_subject",
        "personal_data_requests",
        ["subject_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_pd_requests_subject", table_name="personal_data_requests")
    op.drop_index("ix_pd_requests_overdue_candidates", table_name="personal_data_requests")
    op.drop_index("ix_pd_requests_active", table_name="personal_data_requests")
    op.drop_index("ix_pd_requests_created_id", table_name="personal_data_requests")
    op.drop_table("personal_data_requests")
