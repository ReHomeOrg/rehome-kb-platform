"""Build SystemConfig view from Settings (#229).

Pure function — без I/O. Derives 5 sub-blocks из текущего runtime Settings'а.
Null поля mean «no value configured» (admin UI рендерит «—»).
"""

from __future__ import annotations

from src.api.admin.schemas import (
    SystemConfig,
    SystemConfigLlm,
    SystemConfigModeration,
    SystemConfigRateLimits,
    SystemConfigWebhooks,
)
from src.api.config import Settings


def build_system_config(settings: Settings) -> SystemConfig:
    """Возвращает SystemConfig projection текущего env-config'а.

    Feature-flags taxonomy (стабильный список — admin UI расчитывает на
    presence of keys):
    - `rag` — `RAG_ENABLED` (kb-search Stage 1).
    - `metrics_endpoint` — `METRICS_ENABLED` (/metrics gate).
    - `webhook_worker` — `WEBHOOK_WORKER_ENABLED` (delivery worker).
    - `minio` — `MINIO_ENABLED` (documents storage).
    - `rerank` — `RERANK_ENABLED` (cross-encoder re-ranking).
    """
    feature_flags = {
        "rag": settings.rag_enabled,
        "metrics_endpoint": settings.metrics_enabled,
        "webhook_worker": settings.webhook_worker_enabled,
        "minio": settings.minio_enabled,
        "rerank": settings.rerank_enabled,
    }

    return SystemConfig(
        rate_limits=SystemConfigRateLimits(),  # all null — see schemas docstring
        feature_flags=feature_flags,
        llm_config=SystemConfigLlm(
            active_provider=settings.llm_provider,
            max_context_tokens=settings.llm_max_tokens,
            # `fallback_provider` / `ab_test_split` / `temperature` — null
            # до landing'а multi-provider routing logic.
        ),
        moderation=SystemConfigModeration(),  # null — no moderation feature
        webhooks=SystemConfigWebhooks(
            max_retries=settings.webhook_max_attempts,
            timeout_seconds=settings.webhook_delivery_timeout_seconds,
        ),
    )


__all__ = ["build_system_config"]
