"""chat_escalations table

Revision ID: 0010_chat_escalations
Revises: 0009_chat_sessions_messages
Create Date: 2026-05-12 17:00:00.000000

Эскалация chat-сессии на оператора (E3.6 #71). Каждый POST /escalate
создаёт row; ID = ticket_id в API response. CASCADE при удалении
сессии. Status transitions (`in_progress → resolved`) — backlog
(E6 Admin или kb-monitoring).

CHECK constraints на priority и status синхронизируются с
`ChatEscalation.allowed_priorities()`/`allowed_statuses()` через
test_models_check_sync.py.

INDICES:
- `(session_id)` — lookup per-session escalations (backlog admin).
- `(status, priority)` — для очереди обработки support team'ом
  («покажи все pending high → normal → low»).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_chat_escalations"
down_revision: str | None = "0009_chat_sessions_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_escalations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "priority",
            sa.String(length=8),
            server_default=sa.text("'normal'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high')",
            name="ck_chat_escalations_priority",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'resolved')",
            name="ck_chat_escalations_status",
        ),
    )
    op.create_index(
        "ix_chat_escalations_session_id", "chat_escalations", ["session_id"]
    )
    op.create_index(
        "ix_chat_escalations_status_priority",
        "chat_escalations",
        ["status", "priority"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_escalations_status_priority", table_name="chat_escalations")
    op.drop_index("ix_chat_escalations_session_id", table_name="chat_escalations")
    op.drop_table("chat_escalations")
