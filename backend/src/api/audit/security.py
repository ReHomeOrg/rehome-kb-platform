"""Security event helper для `audit.security_event` webhook (#223, ТЗ §5.1).

Идея: thin layer над `WebhookEventDispatcher` для emit'а security-инцидентов.
В отличие от обычных audit-row'ов (которые persistятся в той же транзакции,
что и trigger), security events — observability signal'ы (SIEM/Loki/alerting).
Они НЕ привязаны к user-facing транзакции и swallow'ят ошибки — мы не должны
fail'ить request только потому что webhook dispatcher down.

Зачем отдельный path помимо AuditLog:
- AuditLog отражает успешные изменения state'а. Security event — это
  *попытка* действия, которая может быть rejected (403). Записывать в
  audit_log как «archived/updated/...» неверно — изменений state не было.
- Сторонние SIEM (Wazuh, Splunk) consume'ят webhook fanout легче чем
  ходить в PostgreSQL.

Severity (см. ТЗ §5.1):
- `info` — observed activity без явной abuse-семантики (e.g., user пробует
  фичу outside свой scope первый раз).
- `warning` — single suspicious attempt (target_bypass / body_mismatch).
- `critical` — confirmed abuse (rate-limit triggered, brute force —
  detection logic пока не landed'ится, оставлено для follow-up).

Зачем не InfoSec через middleware с auto-emit на 401/403:
- 401/403 hit'ы повсеместны (random scanner, expired token). Auto-emit
  → noise > signal. Explicit опто-in в конкретных code paths (только
  там где writer ATTEMPTING explicit privilege escalation) даёт
  actionable feed.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from src.api.webhooks.dispatcher import WebhookEventDispatcher

logger = logging.getLogger(__name__)


class SecurityEventType(StrEnum):
    """Catalog security event types.

    Расширяется по мере landing'а новых wire-up'ов. Не expose'нём за пределы
    `audit.security_event` payload `event_type` field — backend internal
    taxonomy.
    """

    # Writer попытался установить article.access_level / другой ресурс
    # в scope, к которому у него самого нет доступа. ADR-0003 target-check.
    AUTH_TARGET_BYPASS = "auth.target_bypass"

    # Idempotency-Key replay с другим body (Stripe-style 409).
    # Хорошо tracking'ом для detection'а replay-abuse попыток.
    IDEMPOTENCY_BODY_MISMATCH = "idempotency.body_mismatch"


class SecuritySeverity(StrEnum):
    """Trichotomy для severity field — fixed cardinality, SIEM-friendly."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


_EVENT_NAME = "audit.security_event"


async def report_security_event(
    dispatcher: WebhookEventDispatcher,
    *,
    event_type: SecurityEventType,
    severity: SecuritySeverity,
    details: dict[str, Any],
) -> None:
    """Fire `audit.security_event` webhook (ТЗ §5.1).

    Payload: `{event_type, severity, details}` — exactly per ТЗ. `details`
    callers ответственны за non-PII content: actor_sub (Keycloak UUID OK),
    requested resource id (slug OK), attempted target scope. Никаких
    plaintext payloads / passwords / личных данных.

    Swallow'ит exceptions — webhook dispatch не должен fail'ить request
    flow (security event — observability, не enforcement).
    """
    try:
        await dispatcher.dispatch(
            event_type=_EVENT_NAME,
            payload={
                "event_type": event_type.value,
                "severity": severity.value,
                "details": details,
            },
        )
    except Exception:
        logger.exception(
            "security_event.dispatch_failed",
            extra={
                "event_type": event_type.value,
                "severity": severity.value,
            },
        )


__all__ = [
    "SecurityEventType",
    "SecuritySeverity",
    "report_security_event",
]
