"""articles.tags lowercase normalization (#346)

Revision ID: 0029_articles_tags_lowercase
Revises: 0028_audit_log_keyset_index
Create Date: 2026-05-26 02:00:00.000000

Backfill: приводит `articles.tags` JSONB array к lowercase + dedupe (case-
insensitive). До этой миграции `Договор != договор` — статьи с mixed-case
tags не находились по lowercase query.

После миграции:
- Storage: lowercase only (`["договор", "сервисный-платёж"]`).
- Input boundary normalization (Pydantic validator + router `_parse_tags`)
  гарантирует, что новые INSERT/UPDATE придут уже lowercase.
- GIN containment match (`@>`) корректно matches'ит lowercase queries
  против lowercase storage.

DISTINCT lower(value) гарантирует, что `["Договор", "договор"]` свернётся
в `["договор"]` (case-insensitive uniqueness). Order не сохраняется
(jsonb_agg в JSONB порядке) — для AND-containment queries это не важно.

NULL tags (defensive, не должно быть — server_default '[]'::jsonb с #31)
не трогаем. Empty arrays проходят сквозь NO-OP.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029_articles_tags_lowercase"
down_revision: str | None = "0028_audit_log_keyset_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE articles
        SET tags = COALESCE(
            (
                SELECT jsonb_agg(DISTINCT lower(value))
                FROM jsonb_array_elements_text(tags) AS value
            ),
            '[]'::jsonb
        )
        WHERE tags IS NOT NULL
          AND jsonb_typeof(tags) = 'array'
          AND tags <> '[]'::jsonb
        """
    )


def downgrade() -> None:
    # Нет downgrade — lossy преобразование (lowercase'нутый case не
    # восстановить). Re-running upgrade'а идемпотентна (lower(lower)=lower).
    pass
