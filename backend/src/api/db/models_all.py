"""Единая точка импорта всех ORM-моделей.

Alembic autogenerate видит только те таблицы, чьи модели импортированы
до построения `Base.metadata`. Этот файл аккумулирует импорты — добавляйте
новую модель сюда при появлении.
"""

from src.api.admin.users_models import KbUser
from src.api.articles.models import Article, ArticleVersion
from src.api.audit.models import AuditLog
from src.api.categories.models import Category
from src.api.chat.models import ChatEscalation, ChatMessage, ChatSession
from src.api.collaborators.models import Collaborator, CollaboratorReview, PremisesCollaborator
from src.api.collaborators.service_orders_models import ServiceOrder
from src.api.documents.models import Document
from src.api.idempotency.models import IdempotencyKey
from src.api.search.models import ArticleEmbedding
from src.api.search.query_log import SearchQueryLog
from src.api.webhooks.models import Webhook, WebhookDelivery

__all__ = [
    "Article",
    "ArticleEmbedding",
    "ArticleVersion",
    "AuditLog",
    "Category",
    "ChatEscalation",
    "ChatMessage",
    "ChatSession",
    "Collaborator",
    "CollaboratorReview",
    "Document",
    "IdempotencyKey",
    "KbUser",
    "PremisesCollaborator",
    "SearchQueryLog",
    "ServiceOrder",
    "Webhook",
    "WebhookDelivery",
]
