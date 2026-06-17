"""Audit action constants (E4.x #102).

Чтобы action-strings и resource_types жили в одном месте, не разбегаясь
по router'ам как magic literals. Webhook + chat actions добавляются сюда
по мере landing'а соответствующих audit-вызовов.
"""

from typing import Final

# Resource types.
RESOURCE_ARTICLE: Final = "article"
RESOURCE_WEBHOOK: Final = "webhook"
RESOURCE_CHAT_SESSION: Final = "chat_session"
RESOURCE_PREMISES_CARD: Final = "premises_card"
RESOURCE_HR_EMPLOYEE: Final = "hr_employee"
RESOURCE_ARTICLE_QUESTION: Final = "article_question"

# Article actions.
ACTION_ARTICLES_CREATED: Final = "articles.created"
ACTION_ARTICLES_UPDATED: Final = "articles.updated"
ACTION_ARTICLES_ARCHIVED: Final = "articles.archived"

# Article Q&A actions (TZ §2, 2026-05-28). Metadata НЕ содержит body
# (user-supplied text → PII risk если log leak).
ACTION_ARTICLE_QUESTION_SUBMITTED: Final = "article.question.submitted"
ACTION_ARTICLE_QUESTION_ANSWERED: Final = "article.question.answered"
ACTION_ARTICLE_QUESTION_DISMISSED: Final = "article.question.dismissed"

# Webhook actions.
ACTION_WEBHOOKS_CREATED: Final = "webhooks.created"
ACTION_WEBHOOKS_DELETED: Final = "webhooks.deleted"
ACTION_WEBHOOKS_TESTED: Final = "webhooks.tested"

# Chat actions.
ACTION_CHAT_ESCALATED: Final = "chat.escalated"

# Chat unanswered query capture (2026-05-29). Metadata содержит
# `chat_session_id` + (on attach) `article_slug` + `question_id`. НЕ
# содержит query body (масked, но ПДн-aware design — body живёт
# в `chat_unanswered_queries.query_masked`, доступном только staff_admin).
RESOURCE_CHAT_UNANSWERED: Final = "chat_unanswered"
ACTION_CHAT_UNANSWERED_CAPTURED: Final = "chat.unanswered.captured"
ACTION_CHAT_UNANSWERED_ATTACHED: Final = "chat.unanswered.attached"
ACTION_CHAT_UNANSWERED_DISMISSED: Final = "chat.unanswered.dismissed"

# Premises actions (#148, PZ §5 write side).
ACTION_PREMISES_CREATED: Final = "premises.created"
ACTION_PREMISES_UPDATED: Final = "premises.updated"
ACTION_PREMISES_ARCHIVED: Final = "premises.archived"

# HR actions (#150, PZ §7).
# Все read'ы employee records audit'ятся (PZ §7 — журналирование всех
# просмотров для ФЗ-152 compliance).
ACTION_HR_EMPLOYEE_VIEWED: Final = "hr.employee.viewed"
ACTION_HR_EMPLOYEE_CREATED: Final = "hr.employee.created"
ACTION_HR_EMPLOYEE_UPDATED: Final = "hr.employee.updated"
ACTION_HR_EMPLOYEE_ARCHIVED: Final = "hr.employee.archived"
# Stage 2 (#234, ADR-0018) — ПДн encryption. `pii_accessed` пишется на
# каждый GET / list где fields декрипту'ются (compliance trail);
# `pii_updated` — на write c set/clear любого encrypted поля. Metadata
# хранит только ИМЕНА полей, НЕ их значения (анти-leak в audit_log).
ACTION_HR_EMPLOYEE_PII_ACCESSED: Final = "hr.employee.pii_accessed"
ACTION_HR_EMPLOYEE_PII_UPDATED: Final = "hr.employee.pii_updated"

# Document file actions (#214, ADR-0012). Metadata machine-level only —
# no filename / no content (анти-leak PII в audit_log JSONB).
RESOURCE_DOCUMENT: Final = "document"
ACTION_DOCUMENTS_CREATED: Final = "documents.created"
ACTION_DOCUMENTS_FILE_DOWNLOADED: Final = "documents.file.downloaded"
ACTION_DOCUMENTS_FILE_UPLOADED: Final = "documents.file.uploaded"
ACTION_DOCUMENTS_FILE_ARCHIVED: Final = "documents.file.archived"

# Anon chat actor format: `"anon:" + session_token[:N]`. 8 hex chars = 32 bits
# of entropy — достаточно для audit uniqueness, минимально раскрывает токен.
ANON_ACTOR_TOKEN_PREFIX_LEN: Final = 8


def format_anon_actor_sub(token: object) -> str:
    """`anon:<prefix>` actor_sub representation для chat anon flow.

    Single source of truth — должен возвращать ту же строку для audit-log
    (`router.py::post_escalate`) и idempotency PK (`chat/idempotency.py`),
    иначе lookup'ы desync'нутся. `token` принимается как opaque object
    (обычно UUID) — рендерится через `str(token)`.
    """
    return f"anon:{str(token)[:ANON_ACTOR_TOKEN_PREFIX_LEN]}"


# Collaborators actions (ADR-0014, ТЗ §10). Metadata содержит type/group
# — для audit поиска по типам коллаборантов. ПДн (контактные ФИО,
# юр.реквизиты) в audit НЕ пишем (есть в `collaborators.audit_log`
# JSONB колонке, но только для staff_admin).
RESOURCE_COLLABORATOR: Final = "collaborator"
ACTION_COLLABORATOR_CREATED: Final = "collaborator.created"
ACTION_COLLABORATOR_UPDATED: Final = "collaborator.updated"
ACTION_COLLABORATOR_ARCHIVED: Final = "collaborator.archived"
# Slice 2 lifecycle (ADR-0014 §5). Transition events отдельно от updated
# для удобства аудита и compliance reporting.
ACTION_COLLABORATOR_ACTIVATED: Final = "collaborator.activated"
ACTION_COLLABORATOR_SUSPENDED: Final = "collaborator.suspended"
# Slice 3 (ADR-0015, ТЗ §10.8). Public onboarding endpoint + portal-access
# tier change. IP hashed в metadata (ФЗ-152).
ACTION_COLLABORATOR_ONBOARDED: Final = "collaborator.onboarded"
ACTION_COLLABORATOR_PORTAL_ACCESS_CHANGED: Final = "collaborator.portal_access.changed"

# Admin operational actions (#238) — cache invalidation, reindex triggers.
# Metadata содержит scope; не содержит counts (статистика — в admin_tasks
# row + Prometheus). Audit trail используется для compliance reporting:
# «кто triggered reindex / cache flush».
RESOURCE_ADMIN_CACHE: Final = "admin_cache"
RESOURCE_ADMIN_TASK: Final = "admin_task"
ACTION_ADMIN_CACHE_INVALIDATED: Final = "admin.cache.invalidated"
ACTION_ADMIN_REINDEX_TRIGGERED: Final = "admin.reindex.triggered"
# `audit_log.exported` (#239) — мета-audit: фиксируем кто запросил
# export аудит-лога (для регуляторного запроса). Metadata содержит format
# + reason; filters payload — в admin_tasks.params (для replay).
ACTION_ADMIN_AUDIT_LOG_EXPORTED: Final = "admin.audit_log.exported"
# system_config updates (#264, ADR-0019). Metadata содержит keys list +
# (для PUT /admin/llm/active) provider_id + reason. NEVER хранит values
# (могут быть допущены sensitive значения через allowlist; values
# доступны в system_config table напрямую для compliance audit).
RESOURCE_ADMIN_SYSTEM_CONFIG: Final = "admin_system_config"
ACTION_ADMIN_SYSTEM_CONFIG_UPDATED: Final = "admin.system_config.updated"

# Category admin CRUD (#355, ADR-0024). Metadata содержит fields changed
# (parent_id renames, title changes) — НЕ описание (admin может оставить
# title с PII если сам захочет; не наш business). Soft-delete event
# `archived` отдельно от updated для compliance review.
RESOURCE_ADMIN_CATEGORY: Final = "admin_category"
ACTION_ADMIN_CATEGORY_CREATED: Final = "admin.category.created"
ACTION_ADMIN_CATEGORY_UPDATED: Final = "admin.category.updated"
ACTION_ADMIN_CATEGORY_ARCHIVED: Final = "admin.category.archived"
