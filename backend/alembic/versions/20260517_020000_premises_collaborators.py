"""premises_collaborators junction — Slice 5 (ТЗ §10.6, API §3.10.4)

Revision ID: 0021_premises_collaborators
Revises: 0020_collaborators_portal_access
Create Date: 2026-05-17 02:00:00.000000

Many-to-many между premises_cards и collaborators. Один коллаборант
обслуживает множество объектов; один объект — множество коллаборантов
разных ролей (УК + аварийка + клининг и т.п.).

`role` — short freeform string (default_uk / emergency_water / plumber /
electrician / cleaner ...). Не enum — слишком много вариаций, ТЗ §10.6
даёт только примеры.

`priority` — для emergency-сервисов (1 = первый звонок, 2 = резерв).
Default 1.

Composite uniqueness: (premises_id, collaborator_id, role) — один
коллаборант может быть на одном объекте в нескольких ролях
(e.g. "default_uk" + "emergency_water" одной УК).

CASCADE поведение:
- premises_cards.delete (нет soft delete — premises archived через status)
  → orphan junction строки сохраняются для исторического контекста.
- collaborators.archive → junction остаётся (ТЗ §3.10.1: "Привязки
  сохраняются для исторического контекста").
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_premises_collaborators"
down_revision: str | None = "0020_collaborators_portal_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "premises_collaborators",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "premises_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("premises_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collaborator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collaborators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="1"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        # JWT sub of staff кто назначил.
        sa.Column("assigned_by", sa.String(length=255), nullable=False),
        # Композитная уникальность: один коллаборант + одна роль на объект.
        sa.UniqueConstraint(
            "premises_id",
            "collaborator_id",
            "role",
            name="uq_premises_collaborators_triplet",
        ),
        # Priority >= 1 (1 = primary). Защита от accidental 0/-1.
        sa.CheckConstraint("priority >= 1", name="ck_premises_collaborators_priority"),
    )

    # Index for "show all collaborators of premises X" — основной UC
    # (ТЗ §10.7: жилец видит контакты).
    op.create_index(
        "ix_premises_collaborators_premises_priority",
        "premises_collaborators",
        ["premises_id", "priority"],
    )
    # Reverse: "show all premises served by collaborator X" — для admin
    # analytics (Slice 4 metrics potentially).
    op.create_index(
        "ix_premises_collaborators_collaborator",
        "premises_collaborators",
        ["collaborator_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_premises_collaborators_collaborator", table_name="premises_collaborators")
    op.drop_index(
        "ix_premises_collaborators_premises_priority", table_name="premises_collaborators"
    )
    op.drop_table("premises_collaborators")
