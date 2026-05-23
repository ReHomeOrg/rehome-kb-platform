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

from src.api.admin.llm_providers import KNOWN_LLM_PROVIDER_IDS
from src.api.admin.system_config_models import SystemConfigRow
from src.api.chat.system_prompt import (
    SYSTEM_PROMPT_MAX_LENGTH as _CHAT_SYSTEM_PROMPT_MAX_LENGTH,
)
from src.api.chat.system_prompt import (
    SYSTEM_PROMPT_OVERLAY_KEY as _CHAT_SYSTEM_PROMPT_KEY,
)
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
        # Chat — overlay key + max-length константы owned by chat module
        # (single source of truth, см. chat/system_prompt.py).
        _CHAT_SYSTEM_PROMPT_KEY,
    }
)


class UnknownKeyError(ValueError):
    """422-mapped: caller passed unknown key (not в `MUTABLE_KEYS`)."""

    def __init__(self, keys: list[str]) -> None:
        super().__init__(
            f"Unknown / non-mutable keys: {sorted(keys)}. " f"Allowed: {sorted(MUTABLE_KEYS)}"
        )
        self.keys = keys


class InvalidValueError(ValueError):
    """422-mapped: value не прошёл per-key validation.

    Per-key rules лежат в `_validate_value`; raise с указанием key + reason.
    """

    def __init__(self, key: str, reason: str) -> None:
        super().__init__(f"Invalid value для key '{key}': {reason}")
        self.key = key
        self.reason = reason


def _validate_value(key: str, value: Any) -> None:
    """Per-key value validation. Raise `InvalidValueError` if invalid.

    Расширяется по мере landings новых typed overlay keys. Текущий cover:
    - `chat.system_prompt` — string + non-empty + length cap.
    - `llm_provider` / `llm_fallback_provider` — string + ∈ KNOWN_LLM_PROVIDER_IDS.
    """
    if key == _CHAT_SYSTEM_PROMPT_KEY:
        if not isinstance(value, str):
            raise InvalidValueError(key, "must be string")
        if not value.strip():
            raise InvalidValueError(key, "must be non-empty")
        if len(value) > _CHAT_SYSTEM_PROMPT_MAX_LENGTH:
            raise InvalidValueError(key, f"exceeds max length {_CHAT_SYSTEM_PROMPT_MAX_LENGTH}")
    elif key in ("llm_provider", "llm_fallback_provider"):
        if not isinstance(value, str):
            raise InvalidValueError(key, "must be string")
        if value not in KNOWN_LLM_PROVIDER_IDS:
            raise InvalidValueError(
                key,
                f"unknown provider; allowed: {sorted(KNOWN_LLM_PROVIDER_IDS)}",
            )


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
        for key, value in updates.items():
            _validate_value(key, value)
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
    "InvalidValueError",
    "MUTABLE_KEYS",
    "SystemConfigRepository",
    "UnknownKeyError",
    "get_system_config_repository",
]
