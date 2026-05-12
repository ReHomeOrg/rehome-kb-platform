"""SQLAlchemy ORM модель для idempotency_keys (E5.1 #44).

См. миграцию `0005_idempotency_keys.py` для DDL details.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, PrimaryKeyConstraint, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.api.db.base import Base


class IdempotencyKey(Base):
    """Запись response cache для retry-safety.

    Composite PK `(key, request_path, actor_sub)`:
    - `key` — UUID от клиента (header `Idempotency-Key`).
    - `request_path` — позволяет тот же key для разных endpoint'ов.
    - `actor_sub` — Keycloak `sub`; защита от cross-actor leakage.

    `request_body_hash` — sha256(raw request body bytes); 409 при retry
    с тем же key но другим body.
    """

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_path: Mapped[str] = mapped_column(String(500), nullable=False)
    actor_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    request_body_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    response_headers: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        PrimaryKeyConstraint("key", "request_path", "actor_sub", name="pk_idempotency_keys"),
    )

    def __repr__(self) -> str:  # pragma: no cover (debug only)
        return f"<IdempotencyKey key={self.key!r} path={self.request_path!r}>"
