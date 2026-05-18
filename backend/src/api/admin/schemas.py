"""Pydantic schemas для /api/v1/admin/* (OpenAPI 04 §AdminStats / #227).

`AdminStats` — aggregator response с 4 sub-блоками: requests, chat,
content, security. Поля где данных ещё нет (нет соответствующих таблиц)
остаются с default zero / null — frontend нормально показывает «no data».
"""

from __future__ import annotations

from datetime import datetime

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


__all__ = [
    "AdminStats",
    "AdminStatsChat",
    "AdminStatsContent",
    "AdminStatsPeriod",
    "AdminStatsRequests",
    "AdminStatsSecurity",
]
