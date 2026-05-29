"""chat_unanswered_queries — capture chat queries без RAG hits

Revision ID: 0034_chat_unanswered_queries
Revises: 0033_article_question_embeddings
Create Date: 2026-05-29 02:00:00.000000

ТЗ Чат-поиск §5.1: когда RAG не нашёл relevant chunks для chat query,
текущая система fire'ит `chat.no_answer` webhook (для external
analytics) но не хранит запрос внутри платформы. Новая таблица —
internal capture queue для admin moderation: staff видит «незакрытые»
запросы и решает либо attach их как PENDING ArticleQuestion под
конкретной статьёй, либо dismiss как out-of-scope.

Schema:
- `id UUID PK`
- `query_masked TEXT NOT NULL` — user query AFTER mask_pii (ФЗ-152). Cap
  500 chars enforced на router/repository level.
- `author_sub TEXT NOT NULL` — chat owner sub (Keycloak UUID или
  `anon:<prefix>`). Mirror'ит attribution chain существующих audit rows.
- `chat_session_id UUID NULL FK chat_sessions(id) ON DELETE SET NULL`
  — preserve analytics row даже после chat retention worker'а
  (ADR-0026, ФЗ-152 right-to-forget удаляет session, но история
  unanswered queries остаётся для content-gap analysis).
- `status TEXT NOT NULL DEFAULT 'NEW'` — `NEW`/`ATTACHED`/`DISMISSED`.
- `attached_question_id UUID NULL FK article_questions(id) ON DELETE
  SET NULL` — set при ATTACHED.
- `attached_article_slug TEXT NULL` — denormalized для admin list
  display (избегаем JOIN articles ради slug). При archive article'а
  slug остаётся historical pointer.
- `dismiss_reason TEXT NULL` — internal moderation note, DISMISSED only.
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `attached_at TIMESTAMPTZ NULL`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

CHECK constraint — all-or-nothing на ATTACHED state (mirror'ит
ck_article_questions_answered_consistency pattern, PR #347):
   ATTACHED → attached_question_id + attached_at NOT NULL;
   NEW/DISMISSED → both NULL.

Indexes:
- `ix_chat_unanswered_queries_status_created` (status, created_at DESC)
  — admin moderation queue hot path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0034_chat_unanswered_queries"
down_revision: str | None = "0033_article_question_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_unanswered_queries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("query_masked", sa.Text(), nullable=False),
        sa.Column("author_sub", sa.Text(), nullable=False),
        sa.Column(
            "chat_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'NEW'"),
        ),
        sa.Column(
            "attached_question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("article_questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("attached_article_slug", sa.Text(), nullable=True),
        sa.Column("dismiss_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("attached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('NEW','ATTACHED','DISMISSED')",
            name="ck_chat_unanswered_queries_status",
        ),
        # All-or-nothing на ATTACHED state.
        sa.CheckConstraint(
            "(status = 'ATTACHED' AND attached_question_id IS NOT NULL "
            "AND attached_at IS NOT NULL) "
            "OR (status != 'ATTACHED' AND attached_question_id IS NULL "
            "AND attached_at IS NULL)",
            name="ck_chat_unanswered_queries_attached_consistency",
        ),
    )

    # Admin moderation queue.
    op.create_index(
        "ix_chat_unanswered_queries_status_created",
        "chat_unanswered_queries",
        ["status", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_unanswered_queries_status_created",
        table_name="chat_unanswered_queries",
    )
    op.drop_table("chat_unanswered_queries")
