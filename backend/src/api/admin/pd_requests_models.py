"""PersonalDataRequest ORM model (#232, OpenAPI §PersonalDataRequest).

ФЗ-152 §15: subject access requests (SAR) — provide / correct / delete /
transfer. Срок ответа: 30 days от `created_at`.

Status lifecycle:
  NEW → IN_PROGRESS → COMPLETED | REJECTED
  NEW / IN_PROGRESS → OVERDUE (auto, через background worker — backlog)

Terminal: COMPLETED / REJECTED — set'ят `completed_at`.
OVERDUE — auto-status; не set'ит completed_at (заявка ещё «висит»,
просто просрочена).
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base

PD_REQUEST_TYPES: Final[tuple[str, ...]] = ("provide", "correct", "delete", "transfer")
PD_REQUEST_STATUSES: Final[tuple[str, ...]] = (
    "NEW",
    "IN_PROGRESS",
    "COMPLETED",
    "REJECTED",
    "OVERDUE",
)

# Terminal statuses — completed_at обязан быть set.
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({"COMPLETED", "REJECTED"})

# Valid manual transitions (background OVERDUE auto-set — отдельный path).
# COMPLETED / REJECTED — terminal, без outgoing edges (reopen = new request).
ALLOWED_MANUAL_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "NEW": frozenset({"IN_PROGRESS", "REJECTED"}),
    "IN_PROGRESS": frozenset({"COMPLETED", "REJECTED"}),
    "OVERDUE": frozenset({"IN_PROGRESS", "COMPLETED", "REJECTED"}),
    "COMPLETED": frozenset(),
    "REJECTED": frozenset(),
}


class PersonalDataRequest(Base):
    """ПДн subject request (ФЗ-152 §15)."""

    __tablename__ = "personal_data_requests"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="NEW")
    subject_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    subject_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)),
        nullable=False,
        default=list,
        server_default=text("ARRAY[]::uuid[]"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    __table_args__ = (
        CheckConstraint(
            f"type IN ({', '.join(repr(v) for v in PD_REQUEST_TYPES)})",
            name="ck_pd_requests_type",
        ),
        CheckConstraint(
            f"status IN ({', '.join(repr(v) for v in PD_REQUEST_STATUSES)})",
            name="ck_pd_requests_status",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PersonalDataRequest id={self.id} type={self.type} " f"status={self.status}>"


__all__ = [
    "ALLOWED_MANUAL_TRANSITIONS",
    "PD_REQUEST_STATUSES",
    "PD_REQUEST_TYPES",
    "PersonalDataRequest",
    "TERMINAL_STATUSES",
]
