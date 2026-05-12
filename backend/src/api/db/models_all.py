"""Единая точка импорта всех ORM-моделей.

Alembic autogenerate видит только те таблицы, чьи модели импортированы
до построения `Base.metadata`. Этот файл аккумулирует импорты — добавляйте
новую модель сюда при появлении.
"""

from src.api.articles.models import Article, ArticleVersion
from src.api.categories.models import Category
from src.api.idempotency.models import IdempotencyKey

__all__ = ["Article", "ArticleVersion", "Category", "IdempotencyKey"]
