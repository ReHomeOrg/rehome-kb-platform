"""collaborator_reviews — Slice 6 (ТЗ §3.10.5)

Revision ID: 0022_collaborator_reviews
Revises: 0021_premises_collaborators
Create Date: 2026-05-17 03:00:00.000000

Отзывы пользователей о коллаборанте: rating 1-5 + опциональный комментарий
+ display name (для public-маскинга). `author_sub` — JWT sub автора
(аудиту видно, public response — только маскированный display name).

Per ТЗ §3.10.5: POST доступен tenant/landlord с completed заказом.
Slice 6 — без проверки completion (service_orders нет). Backlog:
добавить FK на service_orders + validation после landing'а Slice 4+.

CASCADE на collaborator → reviews очищаются вместе с коллаборантом.
Unique constraint (collaborator_id, author_sub) — один отзыв на
пользователя на коллаборанта. Изменение — отдельный flow (backlog).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_collaborator_reviews"
down_revision: str | None = "0021_premises_collaborators"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collaborator_reviews",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "collaborator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("collaborators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_sub", sa.String(length=255), nullable=False),
        sa.Column("author_display_name", sa.String(length=100), nullable=True),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        # Один отзыв на user на коллаборанта (edit — backlog).
        sa.UniqueConstraint(
            "collaborator_id", "author_sub", name="uq_reviews_collaborator_author"
        ),
    )
    op.create_index(
        "ix_reviews_collaborator_created",
        "collaborator_reviews",
        ["collaborator_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_collaborator_created", table_name="collaborator_reviews")
    op.drop_table("collaborator_reviews")
