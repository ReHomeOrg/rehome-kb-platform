"""initial articles table

Revision ID: 0001_initial_articles
Revises:
Create Date: 2026-05-11 00:00:00.000000

Создаёт таблицу `articles` (ADR-0003) с:
- CHECK constraints на enum-поля (audience, status, access_level) — это
  гарантирует, что приложение не сможет записать невалидное значение
  в обход Pydantic (defence-in-depth).
- Композитный индекс (status, access_level) — для типичного запроса.
- pgcrypto.gen_random_uuid() — расширение требуется на стороне БД.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_articles"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgcrypto для gen_random_uuid().
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "articles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("audience", sa.String(length=16), nullable=False),
        sa.Column(
            "language",
            sa.String(length=8),
            nullable=False,
            server_default=sa.text("'ru'"),
        ),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("access_level", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("slug", name="uq_articles_slug"),
        # CHECK constraints — БД отвергает запись с невалидным enum-значением
        # даже если ORM/Pydantic будет обойдены.
        sa.CheckConstraint(
            "audience IN ('tenant', 'landlord', 'all', 'staff')",
            name="ck_articles_audience",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')",
            name="ck_articles_status",
        ),
        sa.CheckConstraint(
            "access_level IN ('PUBLIC', 'LOGGED', 'AGENT', 'STAFF', 'LEGAL', 'HR_RESTRICTED')",
            name="ck_articles_access_level",
        ),
    )

    op.create_index("ix_articles_slug", "articles", ["slug"], unique=True)
    op.create_index("ix_articles_category", "articles", ["category"])
    op.create_index("ix_articles_access_level", "articles", ["access_level"])
    op.create_index("ix_articles_status", "articles", ["status"])
    op.create_index(
        "ix_articles_status_access_level",
        "articles",
        ["status", "access_level"],
    )


def downgrade() -> None:
    op.drop_index("ix_articles_status_access_level", table_name="articles")
    op.drop_index("ix_articles_status", table_name="articles")
    op.drop_index("ix_articles_access_level", table_name="articles")
    op.drop_index("ix_articles_category", table_name="articles")
    op.drop_index("ix_articles_slug", table_name="articles")
    op.drop_table("articles")
