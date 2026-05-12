"""chat_sessions + chat_messages tables

Revision ID: 0009_chat_sessions_messages
Revises: 0008_documents_table
Create Date: 2026-05-12 16:00:00.000000

Foundation для E3 Chat MVP (Issue #61). Две таблицы:

1. **chat_sessions** — сессии AI-чата с двойной авторизацией
   (`user_id` JWT sub ИЛИ `session_token` opaque UUID).
2. **chat_messages** — сообщения сессии, CASCADE при удалении session.

TTL: anon 24h, authorized 30d (рассчитывается в Python при create).
Lazy expiry: каждый read фильтрует `expires_at > now() AND deleted_at IS NULL`.

ФЗ-152: soft-delete через `deleted_at`. Physical cleanup — backlog
(background worker для `expires_at < now() OR deleted_at < now() - 30d`).

CHECK constraints:
- `chat_messages.role IN ('user', 'assistant', 'system')` —
  synchronized with `ChatMessage.allowed_roles()` via
  `test_models_check_sync.py`.

INDICES:
- `(user_id, created_at)` — list-user-sessions (future endpoint).
- `(session_id, created_at)` на messages — history retrieval.
- `(expires_at) WHERE deleted_at IS NULL` partial — cleanup-worker (backlog).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_chat_sessions_messages"
down_revision: str | None = "0008_documents_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "session_token",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("session_token", name="uq_chat_sessions_session_token"),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index(
        "ix_chat_sessions_session_token", "chat_sessions", ["session_token"]
    )
    op.create_index(
        "ix_chat_sessions_user_created", "chat_sessions", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_chat_sessions_expires_alive",
        "chat_sessions",
        ["expires_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "chat_messages",
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
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "feedback", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_chat_messages_role",
        ),
    )
    op.create_index(
        "ix_chat_messages_session_created",
        "chat_messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    # FK order: drop messages first (зависит от sessions).
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_expires_alive", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_created", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_session_token", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
