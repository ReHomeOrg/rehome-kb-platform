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

# Anon chat actor format: `"anon:" + session_token[:N]`. 8 hex chars = 32 bits
# of entropy — достаточно для audit uniqueness, минимально раскрывает токен.
ANON_ACTOR_TOKEN_PREFIX_LEN: Final = 8
