"""SystemConfigRow ORM model (#264, ADR-0019).

Single-row JSONB table for writable runtime config overlay. См.
ADR-0019 для дизайна; см. system_config_overlay.py для merge layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class SystemConfigRow(Base):
    """`system_config` table — `id=1` invariant row."""

    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint("id = 1", name="ck_system_config_single_row"),)


__all__ = ["SystemConfigRow"]
