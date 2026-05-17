"""vault_wraps multi-user — group_id now lineage metadata (ADR-0017)

Revision ID: 0023_vault_wraps_multi_user
Revises: 0022_collaborator_reviews
Create Date: 2026-05-17 04:00:00.000000

ADR-0017 supersedes ADR-0011 §«Group keypair»: vault_groups → organizational
primitive only, no crypto state. Sharing с группой = N user_id wraps,
по одному на каждого current member'а (каждый под user.x25519_pubkey).

`group_id` колонка в vault_secret_wraps остаётся как **lineage metadata**:
"этот wrap был добавлен потому что user — member группы G". Не используется
для authorization (только user_id).

Changes:
- DROP CHECK constraint ck_vault_secret_wraps_xor (no longer relevant).
- DELETE rows WHERE user_id IS NULL — group-only wraps больше не имеют
  decrypt path. Safe в Stage 1 (no production data yet).
- ALTER user_id SET NOT NULL.
- Replace PK (secret_id, user_id, group_id) → (secret_id, user_id).
  Per ADR-0017 §B "Decision": один user — один wrap per secret, lineage
  group_id шарится через "first share creator" (rare edge case: user в
  двух группах с тем же secret'ом сохраняет lineage первой группы).
- ix_vault_secret_wraps_group остаётся (partial: WHERE group_id IS NOT NULL).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023_vault_wraps_multi_user"
down_revision: str | None = "0022_collaborator_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop XOR check first так чтобы next op'ы могли violate'ить XOR semantics
    # (i.e., user_id NOT NULL даже если group_id NOT NULL — wraps теперь
    # позволяют BOTH columns set, group_id — lineage).
    op.drop_constraint(
        "ck_vault_secret_wraps_xor",
        "vault_secret_wraps",
        type_="check",
    )

    # Removed group-only rows: они не decryptable никаким client'ом (нет
    # group keypair). Safe в Stage 1 (нет production data). Production
    # operation: проверить пустоту перед migration'ом.
    op.execute("DELETE FROM vault_secret_wraps WHERE user_id IS NULL")

    op.alter_column(
        "vault_secret_wraps",
        "user_id",
        nullable=False,
    )

    # Replace PK: убираем group_id из PK (теперь lineage; nullable не
    # совместим с PK). User уникален per secret.
    op.drop_constraint(
        "pk_vault_secret_wraps",
        "vault_secret_wraps",
        type_="primary",
    )
    op.create_primary_key(
        "pk_vault_secret_wraps",
        "vault_secret_wraps",
        ["secret_id", "user_id"],
    )

    # Old ix_vault_secret_wraps_group уже есть (partial WHERE group_id IS NOT NULL);
    # переиспользуем (не пересоздаём).


def downgrade() -> None:
    op.drop_constraint(
        "pk_vault_secret_wraps",
        "vault_secret_wraps",
        type_="primary",
    )
    op.create_primary_key(
        "pk_vault_secret_wraps",
        "vault_secret_wraps",
        ["secret_id", "user_id", "group_id"],
    )
    op.alter_column(
        "vault_secret_wraps",
        "user_id",
        nullable=True,
    )
    op.create_check_constraint(
        "ck_vault_secret_wraps_xor",
        "vault_secret_wraps",
        "(user_id IS NOT NULL AND group_id IS NULL) "
        "OR (user_id IS NULL AND group_id IS NOT NULL)",
    )
