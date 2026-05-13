"""AuditLog ORM model (E4.x #102).

Один row на одно журналируемое write-действие. Транзакционно с trigger'ом
(тот же AsyncSession + commit) — at-least-once гарантия compliance trail
для ФЗ-152.

ФЗ-152: НЕ храним content (body_markdown, title, summary). Только
metadata: action verb, resource_type/id, actor_sub + произвольный JSONB
со state-deltas (access_level, status — для article's, etc.).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class AuditLog(Base):
    """Compliance trail row для одной write-операции."""

    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    actor_sub: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # "Что сделал user X" — admin lookup.
        Index("ix_audit_log_actor_created", "actor_sub", "created_at"),
        # "Кто менял resource Y" — forensic / Subject Access Request (ФЗ-152).
        Index(
            "ix_audit_log_resource_created",
            "resource_type",
            "resource_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return (
            f"<AuditLog action={self.action!r} resource_type={self.resource_type!r} "
            f"resource_id={self.resource_id!r}>"
        )
