"""OutboxRow ORM (#356, ADR-0026).

Persistent event payload между transactional commit (business write)
и subscriber fan-out (drainer worker).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class OutboxRow(Base):
    """`outbox` table row — webhook event ожидающий fan-out."""

    __tablename__ = "outbox"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    flushed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Partial index для drainer hot path (см. migration 0031).
        Index(
            "ix_outbox_pending",
            "created_at",
            postgresql_where="flushed_at IS NULL",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OutboxRow event={self.event_type!r} flushed={self.flushed_at is not None}>"


__all__ = ["OutboxRow"]
