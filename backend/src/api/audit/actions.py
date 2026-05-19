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

# Article actions.
ACTION_ARTICLES_CREATED: Final = "articles.created"
ACTION_ARTICLES_UPDATED: Final = "articles.updated"
ACTION_ARTICLES_ARCHIVED: Final = "articles.archived"

# Webhook actions.
ACTION_WEBHOOKS_CREATED: Final = "webhooks.created"
ACTION_WEBHOOKS_DELETED: Final = "webhooks.deleted"
ACTION_WEBHOOKS_TESTED: Final = "webhooks.tested"

# Chat actions.
ACTION_CHAT_ESCALATED: Final = "chat.escalated"

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

# Vault actions (#146, ADR-0011).
# Resource — `vault_secret` для secret-level operations, `vault_user` для
# user-level (unlock attempts), `vault_group` для group changes.
RESOURCE_VAULT_SECRET: Final = "vault_secret"
RESOURCE_VAULT_USER: Final = "vault_user"
RESOURCE_VAULT_GROUP: Final = "vault_group"

# `vault.unlock` — success / failure both audited (failed-unlock attempts
# обнаруживают brute-force). `secret.read` пишется даже на metadata read'ы,
# но НЕ на `list` (объём логов взорвётся; статистический pattern detect
# через aggregate'ы).
ACTION_VAULT_UNLOCK_SUCCESS: Final = "vault.unlock.success"
ACTION_VAULT_UNLOCK_FAILED: Final = "vault.unlock.failed"
ACTION_VAULT_SECRET_READ: Final = "vault.secret.read"
ACTION_VAULT_SECRET_CREATED: Final = "vault.secret.created"
ACTION_VAULT_SECRET_UPDATED: Final = "vault.secret.updated"
ACTION_VAULT_SECRET_DELETED: Final = "vault.secret.deleted"
ACTION_VAULT_SHARE_ADDED: Final = "vault.share.added"
ACTION_VAULT_SHARE_REVOKED: Final = "vault.share.revoked"
ACTION_VAULT_GROUP_CREATED: Final = "vault.group.created"
ACTION_VAULT_GROUP_MEMBER_ADDED: Final = "vault.group.member.added"
ACTION_VAULT_GROUP_MEMBER_REMOVED: Final = "vault.group.member.removed"

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
