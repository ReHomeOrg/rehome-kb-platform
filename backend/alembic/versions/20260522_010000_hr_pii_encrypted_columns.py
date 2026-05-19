"""hr_employees — ПДн encrypted columns (#234, ADR-0018)

Revision ID: 0024_hr_pii_encrypted
Revises: 0024_merge_heads
Create Date: 2026-05-22 01:00:00.000000

HR Stage 2 — добавляет 4 BYTEA nullable колонки для encrypted ПДн:
- passport_number_encrypted
- inn_encrypted
- snils_encrypted
- bank_account_encrypted

Encryption: Fernet symmetric (per ADR-0018 Variant A).
Plaintext НЕ хранится — только ciphertext.

NULLABLE = «не заполнено». Stage 1 БД не имела этих колонок (см.
`hr/models.py` docstring); no backfill требуется (0 production rows
с ПДн).

Comments на columns — для DBA / pg_dump readers: явно указывают что
это encrypted ПДн, доступ требует HR_RESTRICTED scope в backend.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024_hr_pii_encrypted"
down_revision: str | None = "0024_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PII_COLUMNS = (
    ("passport_number_encrypted", "Паспортные данные (Fernet)"),
    ("inn_encrypted", "ИНН (Fernet)"),
    ("snils_encrypted", "СНИЛС (Fernet)"),
    ("bank_account_encrypted", "Банковский счёт (Fernet)"),
)


def upgrade() -> None:
    for column_name, comment in _PII_COLUMNS:
        op.add_column(
            "hr_employees",
            sa.Column(
                column_name,
                sa.LargeBinary(),
                nullable=True,
                comment=comment,
            ),
        )


def downgrade() -> None:
    for column_name, _ in _PII_COLUMNS:
        op.drop_column("hr_employees", column_name)
