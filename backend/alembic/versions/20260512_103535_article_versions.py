"""article_versions table

Revision ID: 0004_article_versions
Revises: 0003_articles_tags_gin_index
Create Date: 2026-05-12 10:35:35.000000

Версионирование Article (Issue #36). Каждая write-операция (CREATE/UPDATE/
ARCHIVE) пишет запись в `article_versions` в той же транзакции, что
INSERT/UPDATE articles — атомарно.

Для E2.3 хранятся метаданные:
- `version` — sequential per article, начинается с 1
- `event` — CREATE | UPDATE | ARCHIVE (CHECK constraint, sync с
  Article.allowed_events() через test_models_check_sync)
- `author_sub` — Keycloak `sub` claim писателя
- `changed_at` — `now()` server-side
- `old_*` / `new_*` — дельта access_level и status
- `changes_summary` — текстовый комментарий

Snapshot тела (body_markdown) НЕ хранится — backlog для compliance.

FK с `ON DELETE CASCADE` — при будущем hard-delete статьи версии
уничтожаются. Сейчас delete — soft (status='ARCHIVED'), не актуально.

UNIQUE `(article_id, version)` — гарантия sequential numbering;
concurrent write при race получит IntegrityError → 500 (backlog E5
ETag + advisory lock).

Композитный индекс `(article_id, version DESC)` — для запроса истории
от свежих к старым.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_article_versions"
down_revision: str | None = "0003_articles_tags_gin_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "article_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=16), nullable=False),
        sa.Column("author_sub", sa.String(length=255), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("old_status", sa.String(length=16), nullable=True),
        sa.Column("new_status", sa.String(length=16), nullable=False),
        sa.Column("old_access_level", sa.String(length=20), nullable=True),
        sa.Column("new_access_level", sa.String(length=20), nullable=False),
        sa.Column("changes_summary", sa.Text(), nullable=True),
        sa.UniqueConstraint("article_id", "version", name="uq_article_version"),
        # CHECK constraint синхронизирован с Article.allowed_events() —
        # см. test_models_check_sync.py.
        sa.CheckConstraint(
            "event IN ('CREATE', 'UPDATE', 'ARCHIVE')",
            name="ck_article_versions_event",
        ),
    )
    op.create_index(
        "ix_article_versions_article_version",
        "article_versions",
        ["article_id", sa.text("version DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_article_versions_article_version", table_name="article_versions")
    op.drop_table("article_versions")
