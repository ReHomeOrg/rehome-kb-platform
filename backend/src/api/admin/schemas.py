"""Pydantic schemas для /api/v1/admin/* (OpenAPI 04 §AdminStats / #227).

`AdminStats` — aggregator response с 4 sub-блоками: requests, chat,
content, security. Поля где данных ещё нет (нет соответствующих таблиц)
остаются с default zero / null — frontend нормально показывает «no data».
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminStatsPeriod(BaseModel):
    """Time-window для агрегатов."""

    model_config = ConfigDict(extra="forbid")

    from_: datetime = Field(serialization_alias="from")
    to: datetime


class AdminStatsRequests(BaseModel):
    """Сводка HTTP requests (по endpoint, status).

    Backend хранит per-request метрики в Prometheus, не в БД. Этот блок
    в MVP — нули; integration с Prometheus admin API — backlog (требует
    либо querying Prometheus, либо persisting per-request rows).
    """

    model_config = ConfigDict(extra="forbid")

    total: int = 0
    by_endpoint: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    error_rate_percent: float = 0.0


class AdminStatsChat(BaseModel):
    """Чат-метрики из chat_sessions / chat_messages / chat_escalations."""

    model_config = ConfigDict(extra="forbid")

    sessions: int = 0
    messages: int = 0
    # Доля сессий БЕЗ эскалации = 1 - (escalated / sessions).
    containment_rate: float = 0.0
    # AVG(chat_messages.feedback->>'rating') — only over non-null feedback rows.
    # Rating space: 'up' / 'down' маппится в 1 / 0 для усреднения.
    avg_rating: float | None = None
    # `chat.no_answer` событие не persist'ится в БД (только webhook outbox).
    # MVP value = 0; backlog: добавить counter в metrics или persist в audit_log.
    no_answer_count: int = 0
    escalations: int = 0


class AdminStatsContent(BaseModel):
    """Метрики контента: articles + documents."""

    model_config = ConfigDict(extra="forbid")

    total_articles: int = 0
    total_documents: int = 0
    # `pending_reviews` интерпретируется как articles в status=DRAFT
    # (review queue feature ещё не реализован как отдельная сущность).
    pending_reviews: int = 0


class AdminStatsSecurity(BaseModel):
    """Метрики безопасности.

    В MVP — нули: `security_incidents` и `personal_data_requests` таблиц
    ещё нет (ТЗ §3.11 / §3.12 — отдельные эпики). Frontend показывает
    «0 open / 0 critical / 0 overdue».
    """

    model_config = ConfigDict(extra="forbid")

    open_incidents: int = 0
    critical_incidents: int = 0
    overdue_pd_requests: int = 0


class AdminStats(BaseModel):
    """OpenAPI 04 §AdminStats response."""

    model_config = ConfigDict(extra="forbid")

    period: AdminStatsPeriod
    requests: AdminStatsRequests = Field(default_factory=AdminStatsRequests)
    chat: AdminStatsChat = Field(default_factory=AdminStatsChat)
    content: AdminStatsContent = Field(default_factory=AdminStatsContent)
    security: AdminStatsSecurity = Field(default_factory=AdminStatsSecurity)


# ---------------------------------------------------------------------------
# LLM providers (#228, OpenAPI 04 §listLlmProviders / §LlmProvider)


LlmProviderStatus = Literal["ACTIVE", "INACTIVE", "EXPERIMENTAL"]
LlmHealthStatus = Literal["ok", "degraded", "down"]


class LlmProviderView(BaseModel):
    """One LLM provider entry (OpenAPI 04 §LlmProvider).

    Backend enumeration — статический список known providers; `is_current`
    derive'ится из `Settings.llm_provider`. Cost / health fields — null
    в MVP (нет источника данных: provider price book + health checker —
    backlog).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    vendor: str | None = None
    model: str | None = None
    status: LlmProviderStatus
    is_current: bool = False
    # `cost_per_1m_*_tokens_rub` — financial pricing metadata; backend
    # не имеет authoritative source — null = «не предоставлено».
    cost_per_1m_input_tokens_rub: float | None = None
    cost_per_1m_output_tokens_rub: float | None = None
    max_context_tokens: int | None = None
    supports_streaming: bool | None = None
    # `last_health_check` + `health_status` — backlog (нужен periodic
    # health-poller worker; до landing'а — null).
    last_health_check: datetime | None = None
    health_status: LlmHealthStatus | None = None


class LlmProvidersListResponse(BaseModel):
    """Envelope для GET /admin/llm/providers."""

    data: list[LlmProviderView]


# ---------------------------------------------------------------------------
# System config (#229, OpenAPI 04 §SystemConfig)
#
# Read-only projection текущего runtime config'а (Settings) для admin UI.
# PATCH endpoint deferred: env-based config не mutable at runtime; PATCH
# требует writable `system_config` table — отдельный PR.


class SystemConfigRateLimits(BaseModel):
    """Rate limit thresholds (per OpenAPI).

    Backend пока не имеет explicit rate-limit config в Settings:
    `collaborators.onboarding` использует in-memory 5/hour limit, остальные
    endpoint'ы — без limits. Все поля null до landing'а полноценной
    rate-limit infrastructure.
    """

    model_config = ConfigDict(extra="forbid")

    guest_per_minute: int | None = None
    user_per_minute: int | None = None
    m2m_per_minute: int | None = None
    chat_messages_per_5min: int | None = None


class SystemConfigLlm(BaseModel):
    """LLM-specific runtime config."""

    model_config = ConfigDict(extra="forbid")

    active_provider: str
    # `fallback_provider` / `ab_test_split` / `temperature` — null до
    # landing'а multi-provider routing logic (#258+ stable single-provider
    # MVP). Backlog: env'ы LLM_FALLBACK_PROVIDER etc.
    fallback_provider: str | None = None
    ab_test_split_percent: int | None = None
    max_context_tokens: int | None = None
    temperature: float | None = None


class SystemConfigModeration(BaseModel):
    """Moderation thresholds.

    Backend пока не имеет moderation feature (auto-publish queue / human
    review). Все поля null — будут заполнены когда landит soответствующий
    эпик.
    """

    model_config = ConfigDict(extra="forbid")

    auto_publish_threshold: float | None = None
    require_review_for_categories: list[str] = Field(default_factory=list)


class SystemConfigWebhooks(BaseModel):
    """Webhook delivery config (out of Settings)."""

    model_config = ConfigDict(extra="forbid")

    max_retries: int
    timeout_seconds: float


class SystemConfig(BaseModel):
    """OpenAPI 04 §SystemConfig — read-only projection текущего runtime
    config'а из `Settings` + feature-flags."""

    model_config = ConfigDict(extra="forbid")

    rate_limits: SystemConfigRateLimits = Field(default_factory=SystemConfigRateLimits)
    # Feature flags — derived из соответствующих `_enabled` Settings polей.
    # Subscriber list стабильный: rag_enabled, metrics_enabled,
    # webhook_worker_enabled, minio_enabled.
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    llm_config: SystemConfigLlm
    moderation: SystemConfigModeration = Field(default_factory=SystemConfigModeration)
    webhooks: SystemConfigWebhooks


__all__ = [
    "AdminStats",
    "AdminStatsChat",
    "AdminStatsContent",
    "AdminStatsPeriod",
    "AdminStatsRequests",
    "AdminStatsSecurity",
    "LlmProviderView",
    "LlmProvidersListResponse",
    "SystemConfig",
    "SystemConfigLlm",
    "SystemConfigModeration",
    "SystemConfigRateLimits",
    "SystemConfigWebhooks",
]
