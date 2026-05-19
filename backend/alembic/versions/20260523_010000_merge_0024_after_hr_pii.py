"""Merge alembic 0024_service_orders + 0024_hr_pii_encrypted heads

Revision ID: 0024_post_hr_pii_merge
Revises: 0024_service_orders, 0024_hr_pii_encrypted
Create Date: 2026-05-23 01:00:00.000000

После merge'а PR #270 (service_orders) и PR #279 (hr_pii_encrypted) на
main оказались две головы — оба revise'ят `0024_merge_heads`. Это
ломает `alembic upgrade head` (Integration CI красный).

Этот merge revision — no-op DDL: только унифицирует branch lineage.
Subsequent migrations (security_incidents, pd_requests) chain'ятся
поверх `0024_post_hr_pii_merge`.
"""

from collections.abc import Sequence

revision: str = "0024_post_hr_pii_merge"
down_revision: str | Sequence[str] | None = (
    "0024_service_orders",
    "0024_hr_pii_encrypted",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
