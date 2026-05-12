"""Webhook event types (E5.1 #87).

Source of truth — OpenAPI 04 `WebhookEvent` enum (line 3578-3591).
Mirror в CHECK constraint миграции (через test_models_check_sync).
"""

from enum import StrEnum


class WebhookEvent(StrEnum):
    """Allowed webhook event types — backend trigger'ит подписчиков."""

    ARTICLE_PUBLISHED = "article.published"
    ARTICLE_UPDATED = "article.updated"
    ARTICLE_ARCHIVED = "article.archived"
    DOCUMENT_CREATED = "document.created"
    DOCUMENT_SIGNED = "document.signed"
    CHAT_ESCALATED = "chat.escalated"
    CHAT_NO_ANSWER = "chat.no_answer"
    SEARCH_POPULAR_QUERY = "search.popular_query"
    PREMISES_CARD_UPDATED = "premises_card.updated"
    AUDIT_SECURITY_EVENT = "audit.security_event"
    COLLABORATOR_CREATED = "collaborator.created"


ALLOWED_EVENTS: frozenset[str] = frozenset(e.value for e in WebhookEvent)
