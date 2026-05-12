"""documents table

Revision ID: 0008_documents_table
Revises: 0007_categories_table
Create Date: 2026-05-12 15:00:00.000000

Документы kb-files (Issue #56) — metadata-only. Storage-level access
filter через `confidentiality` enum (PUBLIC/INTERNAL/RESTRICTED).
`signed_by`, `audit_log` хранятся как JSONB и возвращаются только в
detail-response (ФЗ-152: содержат ПДн).

CHECK constraints на category/status/confidentiality синхронизированы
с `Document.allowed_*()` методами (тест `test_models_check_sync`).

INDICES:
- (confidentiality, status, updated_at DESC) — типичный list-запрос.
- category, status, confidentiality, related_entity — отдельные для
  фильтров.

Download endpoint `/{id}/files/{format}` возвращает 501 — реальная
реализация ждёт MinIO в kb-files эпике.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_documents_table"
down_revision: str | None = "0007_categories_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=2), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("counterparty", sa.Text(), nullable=True),
        sa.Column("confidentiality", sa.String(length=16), nullable=False),
        sa.Column("related_entity", sa.String(length=200), nullable=True),
        sa.Column(
            "files",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "signed_by",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "audit_log",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
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
        sa.CheckConstraint(
            "category IN ('A', 'B', 'C', 'D', 'E', 'F')",
            name="ck_documents_category",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'EXPIRED', 'CANCELLED')",
            name="ck_documents_status",
        ),
        sa.CheckConstraint(
            "confidentiality IN ('PUBLIC', 'INTERNAL', 'RESTRICTED')",
            name="ck_documents_confidentiality",
        ),
    )
    op.create_index("ix_documents_category", "documents", ["category"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_confidentiality", "documents", ["confidentiality"])
    op.create_index("ix_documents_related_entity", "documents", ["related_entity"])
    op.create_index(
        "ix_documents_conf_status_updated",
        "documents",
        ["confidentiality", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_conf_status_updated", table_name="documents")
    op.drop_index("ix_documents_related_entity", table_name="documents")
    op.drop_index("ix_documents_confidentiality", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_category", table_name="documents")
    op.drop_table("documents")
