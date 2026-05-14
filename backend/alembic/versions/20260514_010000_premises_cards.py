"""premises_cards foundation

Revision ID: 0015_premises_cards
Revises: 0014_article_embeddings
Create Date: 2026-05-14 01:00:00.000000

PZ §5 «Карточка сдаваемой квартиры». Foundation table — read-side only
в этом PR (#142); write endpoints + per-tenant access в follow-up.

ACCESS MODEL (Stage 1):
- Identification (§5.1) — typed columns. Подмножество (address / status /
  cadastral_number) видимо public; owner / owner_representative /
  current_tenant — STAFF only (содержат ПДн).
- Financial / TenantInfo / Internal — JSONB blocks, STAFF read-only в
  Stage 1. Per-owner / per-tenant access — после landing'а Users /
  Contracts модулей.

STATUS lifecycle: DRAFT → PUBLISHED → RENTED → ARCHIVED (CHECK constraint).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_premises_cards"
down_revision: str | None = "0014_article_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "premises_cards",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("slug", sa.String(200), nullable=False, unique=True),
        # Internal_code — читаемый человеческий идентификатор для staff
        # (например, "СПБ-Купчино-001"). Может быть NULL для draft'ов до
        # ручного заполнения. NOT unique (sequence генерируется операторами).
        sa.Column("internal_code", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        # premises_uuid — link на продуктовую DB (premises module из основной
        # платформы reHome). Опционально: карточка может быть создана раньше
        # чем premises row, или быть legacy без продуктового UUID.
        sa.Column("premises_uuid", postgresql.UUID(as_uuid=True), nullable=True),
        # Identification: typed columns для критичных полей (frequent
        # filtering / sorting). Остальные identification fields в
        # `extra_identification` JSONB (флор, метраж, etc.).
        sa.Column("address", sa.String(500), nullable=False),
        sa.Column("postal_code", sa.String(16), nullable=True),
        sa.Column("cadastral_number", sa.String(64), nullable=True),
        # ПДн blocks — JSONB. NOT NULL с default '{}' чтобы избежать
        # NULL-coercion в Python.
        sa.Column(
            "owner",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "owner_representative",
            postgresql.JSONB,
            nullable=True,
        ),
        sa.Column(
            "current_tenant",
            postgresql.JSONB,
            nullable=True,
        ),
        # §5.2-§5.4 blocks — JSONB opaque в Stage 1.
        sa.Column(
            "financial_data",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tenant_info",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "internal_data",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Free-form identification overflow (этаж, площадь, год постройки,
        # etc.). Здесь, а не в tenant_info, чтобы не путать с §5.3 «инфо
        # жильцу» которая имеет специальный access scope.
        sa.Column(
            "extra_identification",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        # Lifecycle CHECK — экономит DB write на bad status; CHECK
        # дешевле lookup'а в отдельной enum-таблице, и список фиксирован.
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'RENTED', 'ARCHIVED')",
            name="ck_premises_cards_status",
        ),
        sa.CheckConstraint(
            "char_length(slug) BETWEEN 1 AND 200",
            name="ck_premises_cards_slug_length",
        ),
    )
    op.create_index(
        "ix_premises_cards_status",
        "premises_cards",
        ["status"],
    )
    op.create_index(
        "ix_premises_cards_cadastral_number",
        "premises_cards",
        ["cadastral_number"],
    )
    op.create_index(
        "ix_premises_cards_address_trgm",
        "premises_cards",
        ["address"],
    )


def downgrade() -> None:
    op.drop_index("ix_premises_cards_address_trgm", table_name="premises_cards")
    op.drop_index("ix_premises_cards_cadastral_number", table_name="premises_cards")
    op.drop_index("ix_premises_cards_status", table_name="premises_cards")
    op.drop_table("premises_cards")
