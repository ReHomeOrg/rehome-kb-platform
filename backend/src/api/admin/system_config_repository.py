"""SystemConfigRepository (#264, ADR-0019).

Read + atomic-update API над `system_config` row.id=1. Caller passes
flat-key dict в `patch`; unknown keys → `UnknownKeyError` (422 в router).

Allowlist `MUTABLE_KEYS` хранит plain string flat-paths (`"llm_provider"`,
`"feature_flags.rag_enabled"`); dot-notation позволяет nested keys без
nested dicts в JSON payload.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.system_config_models import SystemConfigRow
from src.api.db import get_session

# Allow-listed mutable config keys (см. ADR-0019). Расширяется по мере
# того как admin UI добавляет controls. Secrets / Vault keys / JWT —
# НИКОГДА не в этом списке.
MUTABLE_KEYS: Final[frozenset[str]] = frozenset(
    {
        # LLM
        "llm_provider",
        "llm_fallback_provider",
        # Moderation
        "moderation.auto_publish_threshold",
        # Feature flags
        "feature_flags.rag_enabled",
        "feature_flags.webhook_worker_enabled",
        "feature_flags.metrics_enabled",
    }
)


class UnknownKeyError(ValueError):
    """422-mapped: caller passed unknown key (not в `MUTABLE_KEYS`)."""

    def __init__(self, keys: list[str]) -> None:
        super().__init__(
            f"Unknown / non-mutable keys: {sorted(keys)}. " f"Allowed: {sorted(MUTABLE_KEYS)}"
        )
        self.keys = keys


class SystemConfigRepository:
    """`system_config` table (single row) accessor."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def read(self) -> dict[str, Any]:
        """Returns current overlay dict (data column)."""
        row = await self._get_row()
        return dict(row.data)

    async def patch(
        self,
        updates: dict[str, Any],
        *,
        actor_sub: str,
    ) -> dict[str, Any]:
        """Atomic update: filter allowed keys, replace values, persist.

        Returns `(before, after)` tuple via two dict snapshots — нет: пока
        возвращает only the new `data` dict; before — отдельный read
        перед patch'ом если caller хочет diff (для audit).

        Empty `updates` после filtering → no-op (без INSERT/UPDATE).
        Unknown keys → raise `UnknownKeyError`.
        """
        unknown = [k for k in updates if k not in MUTABLE_KEYS]
        if unknown:
            raise UnknownKeyError(unknown)
        if not updates:
            return await self.read()

        row = await self._get_row()
        # Mutate JSONB dict in-place + flag change for SQLAlchemy.
        new_data = {**row.data, **updates}
        row.data = new_data
        row.updated_by = actor_sub
        await self._session.flush()
        return dict(new_data)

    async def _get_row(self) -> SystemConfigRow:
        stmt = select(SystemConfigRow).where(SystemConfigRow.id == 1)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            # Should never happen — migration инсёртит row.id=1. Defensive
            # fallback: insert лениво.
            row = SystemConfigRow(id=1, data={}, updated_by="lazy_init")
            self._session.add(row)
            await self._session.flush()
        return row


async def get_system_config_repository(
    session: AsyncSession = Depends(get_session),
) -> SystemConfigRepository:
    return SystemConfigRepository(session)


__all__ = [
    "MUTABLE_KEYS",
    "SystemConfigRepository",
    "UnknownKeyError",
    "get_system_config_repository",
]
