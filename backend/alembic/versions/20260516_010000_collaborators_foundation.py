"""collaborators table — foundation (ADR-0014, Slice 1)

Revision ID: 0019_collaborators_foundation
Revises: 0018_premises_search_vector
Create Date: 2026-05-16 01:00:00.000000

Создаёт `collaborators` table для ТЗ §10 (единая сущность для всех
внешних исполнителей платформы reHome). 14 типов, 4 финансовые группы
(A/B/C/D), 5 статусов.

КРИТИЧЕСКИЙ ИНВАРИАНТ ADR-0014 §2: pair (type, financial_group)
жёстко закреплён ТЗ §10.3 — enforced через CHECK constraint в БД.
'other' тип — единственный, который может быть в любой группе
(ТЗ: "Финансовая группа выбирается при заведении, требует ADR").

ADR-0003 enforcement: access_level не отдельная колонка, фильтр
через `financial_group IN (...)` per scope (D→PUBLIC контакт,
A/B/C→staff-only).

JSONB поля: contacts (массив), financial_terms, api_integration, sla,
counterparty_check, audit_log — структура валидируется Pydantic на
API boundary, не DB CHECK (ADR-0014 §4).

Indexes:
- (financial_group, status, updated_at DESC) — типичный list-запрос.
- type, status, service_area — отдельные для фильтров.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_collaborators_foundation"
down_revision: str | None = "0018_premises_search_vector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ТЗ §10.2 enum для type. Любая правка — синхронно в:
#   backend/src/api/collaborators/schemas.py (Literal)
#   docs/handoff/01_postanovka/04_openapi.yaml (enum)
# Drift тест test_collaborators_check_sync verify'ит соответствие.
_TYPES = (
    "management_company",
    "emergency_service",
    "repair_handyman",
    "cleaning",
    "moving",
    "key_delivery",
    "insurance",
    "payment_partner",
    "kyc_provider",
    "edo_provider",
    "sms_voice",
    "it_infrastructure",
    "legal_consultant",
    "other",
)

_FINANCIAL_GROUPS = ("A", "B", "C", "D")
_STATUSES = ("DRAFT", "PENDING_REVIEW", "ACTIVE", "SUSPENDED", "ARCHIVED")
_LEGAL_ENTITY_TYPES = ("individual", "self_employed", "ip", "legal_entity")

# ТЗ §10.3 invariant pairs (type, financial_group). 'other' — wildcard.
_TYPE_GROUP_PAIRS = (
    ("payment_partner", "A"),
    ("kyc_provider", "A"),
    ("sms_voice", "A"),
    ("it_infrastructure", "A"),
    ("edo_provider", "A"),
    ("legal_consultant", "A"),
    ("cleaning", "B"),
    ("moving", "B"),
    ("key_delivery", "B"),
    ("repair_handyman", "B"),
    ("insurance", "C"),
    ("management_company", "D"),
    ("emergency_service", "D"),
)


def _build_type_group_check() -> str:
    """SQL fragment для CHECK invariant (type, financial_group).

    `other` — wildcard (любая группа). Остальные — exactly one group.
    """
    pairs_sql = " OR ".join(
        f"(type = '{t}' AND financial_group = '{g}')" for t, g in _TYPE_GROUP_PAIRS
    )
    return f"({pairs_sql}) OR (type = 'other')"


def upgrade() -> None:
    op.create_table(
        "collaborators",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Identity
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("brand_name", sa.String(length=200), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("financial_group", sa.String(length=1), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        # Legal
        sa.Column("legal_entity_type", sa.String(length=20), nullable=True),
        sa.Column("inn", sa.String(length=20), nullable=True),
        sa.Column("ogrn", sa.String(length=20), nullable=True),
        sa.Column("kpp", sa.String(length=20), nullable=True),
        # Logistics
        sa.Column("service_area", sa.String(length=500), nullable=False),
        sa.Column("working_hours", sa.String(length=200), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("responsible_internal", sa.String(length=200), nullable=True),
        # Contract reference
        sa.Column(
            "contract_document_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "fallback_collaborator_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        # Rating (computed by external aggregator job; column для quick read)
        sa.Column("rating", sa.Numeric(precision=3, scale=2), nullable=True),
        # JSONB — структура валидируется Pydantic (ADR-0014 §4)
        sa.Column(
            "contacts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "financial_terms",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "api_integration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "sla",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "counterparty_check",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "audit_log",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        # CHECK constraints
        sa.CheckConstraint(
            f"type IN ({','.join(repr(t) for t in _TYPES)})",
            name="ck_collaborators_type",
        ),
        sa.CheckConstraint(
            f"financial_group IN ({','.join(repr(g) for g in _FINANCIAL_GROUPS)})",
            name="ck_collaborators_financial_group",
        ),
        sa.CheckConstraint(
            f"status IN ({','.join(repr(s) for s in _STATUSES)})",
            name="ck_collaborators_status",
        ),
        sa.CheckConstraint(
            f"legal_entity_type IS NULL OR legal_entity_type IN "
            f"({','.join(repr(t) for t in _LEGAL_ENTITY_TYPES)})",
            name="ck_collaborators_legal_entity_type",
        ),
        # Invariant: pair (type, financial_group) per ADR-0014 §2
        sa.CheckConstraint(_build_type_group_check(), name="ck_collaborators_type_group_pair"),
    )

    # Indexes — типичные list-запросы (см. ТЗ §10.5).
    op.create_index(
        "ix_collaborators_group_status_updated",
        "collaborators",
        ["financial_group", "status", sa.text("updated_at DESC")],
    )
    op.create_index("ix_collaborators_type", "collaborators", ["type"])
    op.create_index("ix_collaborators_status", "collaborators", ["status"])


def downgrade() -> None:
    op.drop_index("ix_collaborators_status", table_name="collaborators")
    op.drop_index("ix_collaborators_type", table_name="collaborators")
    op.drop_index("ix_collaborators_group_status_updated", table_name="collaborators")
    op.drop_table("collaborators")
