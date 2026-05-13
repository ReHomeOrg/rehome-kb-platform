"""Audit log module (E4.x #102).

Transactional persistence для compliance trail (ФЗ-152).
"""

from src.api.audit.actions import (
    ACTION_ARTICLES_ARCHIVED,
    ACTION_ARTICLES_CREATED,
    ACTION_ARTICLES_UPDATED,
    ACTION_CHAT_ESCALATED,
    ACTION_WEBHOOKS_CREATED,
    ACTION_WEBHOOKS_DELETED,
    ACTION_WEBHOOKS_TESTED,
    RESOURCE_ARTICLE,
    RESOURCE_CHAT_SESSION,
    RESOURCE_WEBHOOK,
)
from src.api.audit.models import AuditLog
from src.api.audit.repository import AuditRepository, get_audit_repository

__all__ = [
    "ACTION_ARTICLES_ARCHIVED",
    "ACTION_ARTICLES_CREATED",
    "ACTION_ARTICLES_UPDATED",
    "ACTION_CHAT_ESCALATED",
    "ACTION_WEBHOOKS_CREATED",
    "ACTION_WEBHOOKS_DELETED",
    "ACTION_WEBHOOKS_TESTED",
    "AuditLog",
    "AuditRepository",
    "RESOURCE_ARTICLE",
    "RESOURCE_CHAT_SESSION",
    "RESOURCE_WEBHOOK",
    "get_audit_repository",
]
