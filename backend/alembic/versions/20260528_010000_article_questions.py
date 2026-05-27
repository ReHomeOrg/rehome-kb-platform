"""article_questions — user Q&A под статьями (TZ §2 community-driven help)

Revision ID: 0032_article_questions
Revises: 0031_outbox
Create Date: 2026-05-28 01:00:00.000000

User-submitted questions on KB articles with staff moderation. Schema:

- `id UUID PK`
- `article_id UUID NOT NULL FK articles(id) ON DELETE CASCADE` — вопросы
  archived вместе с article.
- `author_sub TEXT NOT NULL` — JWT sub автора (Keycloak UUID или
  anon:<prefix> для guest flow).
- `body TEXT NOT NULL` — вопрос (max ~2000 chars enforced на router level).
- `status TEXT NOT NULL CHECK (status IN ('PENDING','ANSWERED','DISMISSED'))`
  — moderation state. Public видит только ANSWERED.
- `answer_body TEXT NULL` — staff answer (только когда status=ANSWERED).
- `answerer_sub TEXT NULL` — JWT sub staff'а который отвечал.
- `dismiss_reason TEXT NULL` — internal moderation note (DISMISSED only,
  НЕ возвращается публично; PII guard).
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `answered_at TIMESTAMPTZ NULL`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` — for updates audit

Indexes:
- `ix_article_questions_article_status` (article_id, status, created_at DESC)
  — hot path query «public ANSWERED list для article slug».
- `ix_article_questions_status_created` (status, created_at DESC) — admin
  moderation queue (status=PENDING ordered newest first).

ФЗ-152 invariants (enforced на router/audit level, не DB):
- `body` / `answer_body` НЕ попадают в audit_log metadata (PII risk —
  user может ввести phone/email).
- ANSWERED становятся публичными — disclaimer на frontend форме.
- DISMISSED не возвращается публично (включая body — author lookup
  возможен через admin trail).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0032_article_questions"
down_revision: str | None = "0031_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "article_questions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_sub", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("answer_body", sa.Text(), nullable=True),
        sa.Column("answerer_sub", sa.Text(), nullable=True),
        sa.Column("dismiss_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','ANSWERED','DISMISSED')",
            name="ck_article_questions_status",
        ),
        # CHECK: ANSWERED обязан иметь answer_body + answerer_sub +
        # answered_at; PENDING / DISMISSED — без answer_body. DISMISSED
        # допустимо с dismiss_reason.
        sa.CheckConstraint(
            "(status = 'ANSWERED' AND answer_body IS NOT NULL AND "
            "answerer_sub IS NOT NULL AND answered_at IS NOT NULL) "
            "OR (status != 'ANSWERED' AND answer_body IS NULL "
            "AND answerer_sub IS NULL AND answered_at IS NULL)",
            name="ck_article_questions_answered_consistency",
        ),
    )

    # Public hot path: ANSWERED для article slug.
    op.create_index(
        "ix_article_questions_article_status",
        "article_questions",
        ["article_id", "status", sa.text("created_at DESC")],
    )
    # Admin moderation queue.
    op.create_index(
        "ix_article_questions_status_created",
        "article_questions",
        ["status", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_article_questions_status_created", table_name="article_questions")
    op.drop_index("ix_article_questions_article_status", table_name="article_questions")
    op.drop_table("article_questions")
