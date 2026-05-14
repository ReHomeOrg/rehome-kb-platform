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

# Anon chat actor format: `"anon:" + session_token[:N]`. 8 hex chars = 32 bits
# of entropy — достаточно для audit uniqueness, минимально раскрывает токен.
ANON_ACTOR_TOKEN_PREFIX_LEN: Final = 8
