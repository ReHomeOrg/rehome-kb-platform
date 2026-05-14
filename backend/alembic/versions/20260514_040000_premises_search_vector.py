"""premises_cards search_vector (FTS) — Cube C #154

Revision ID: 0018_premises_search_vector
Revises: 0017_hr_foundation
Create Date: 2026-05-14 04:00:00.000000

PZ §5 catalog search — Postgres FTS на address + cadastral_number.
Generated column (auto-updated на INSERT/UPDATE), GIN index для O(log)
query.

Weights:
- A: address (primary search target)
- B: cadastral_number (numeric — to_tsvector parsers extract digits)
- C: postal_code

`russian` language config — handles падежи / morfology.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_premises_search_vector"
down_revision: str | None = "0017_hr_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE premises_cards ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('russian', coalesce(address, '')), 'A') ||
            setweight(to_tsvector('russian', coalesce(cadastral_number, '')), 'B') ||
            setweight(to_tsvector('russian', coalesce(postal_code, '')), 'C')
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_premises_cards_search_vector "
        "ON premises_cards USING gin (search_vector)"
    )


def downgrade() -> None:
    op.drop_index("ix_premises_cards_search_vector", table_name="premises_cards")
    op.drop_column("premises_cards", "search_vector")
