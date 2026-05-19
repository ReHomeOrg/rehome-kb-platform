"""Build SystemConfig view from Settings + DB overlay (#229, #264).

ADR-0019 merge layer: env (через `Settings`) — primary source; DB
overlay (allow-listed keys из `system_config.data`) — override.

`build_system_config(settings)` — pure backward-compatible (env-only).
`build_system_config_with_overlay(settings, overlay)` — applies DB layer
поверх env. Router использует второй для GET — read endpoint видит
полное состояние (env + DB).
"""

from __future__ import annotations

from typing import Any

from src.api.admin.schemas import (
    SystemConfig,
    SystemConfigLlm,
    SystemConfigModeration,
    SystemConfigRateLimits,
    SystemConfigWebhooks,
)
from src.api.config import Settings


def _flag(overlay: dict[str, Any], key: str, default: bool) -> bool:
    """Read feature_flag from overlay (`feature_flags.<key>`) or fall back."""
    return bool(overlay.get(f"feature_flags.{key}", default))


def build_system_config(
    settings: Settings,
    overlay: dict[str, Any] | None = None,
) -> SystemConfig:
    """Возвращает SystemConfig projection: env + optional DB overlay.

    Feature-flags taxonomy (стабильный список — admin UI расчитывает на
    presence of keys):
    - `rag` — `RAG_ENABLED` (kb-search Stage 1).
    - `metrics_endpoint` — `METRICS_ENABLED` (/metrics gate).
    - `webhook_worker` — `WEBHOOK_WORKER_ENABLED` (delivery worker).
    - `minio` — `MINIO_ENABLED` (documents storage).
    - `rerank` — `RERANK_ENABLED` (cross-encoder re-ranking).

    Overlay keys (см. ADR-0019 / `MUTABLE_KEYS`): `llm_provider`,
    `llm_fallback_provider`, `moderation.auto_publish_threshold`,
    `feature_flags.{rag_enabled, webhook_worker_enabled, metrics_enabled}`.
    """
    overlay = overlay or {}

    feature_flags = {
        "rag": _flag(overlay, "rag_enabled", settings.rag_enabled),
        "metrics_endpoint": _flag(overlay, "metrics_enabled", settings.metrics_enabled),
        "webhook_worker": _flag(overlay, "webhook_worker_enabled", settings.webhook_worker_enabled),
        "minio": settings.minio_enabled,
        "rerank": settings.rerank_enabled,
    }

    return SystemConfig(
        rate_limits=SystemConfigRateLimits(),
        feature_flags=feature_flags,
        llm_config=SystemConfigLlm(
            active_provider=str(overlay.get("llm_provider", settings.llm_provider)),
            fallback_provider=overlay.get("llm_fallback_provider"),
            max_context_tokens=settings.llm_max_tokens,
        ),
        moderation=SystemConfigModeration(
            auto_publish_threshold=overlay.get("moderation.auto_publish_threshold"),
        ),
        webhooks=SystemConfigWebhooks(
            max_retries=settings.webhook_max_attempts,
            timeout_seconds=settings.webhook_delivery_timeout_seconds,
        ),
    )


__all__ = ["build_system_config"]
