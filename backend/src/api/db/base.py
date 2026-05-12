"""Declarative Base для SQLAlchemy моделей.

Все ORM-модели наследуются от `Base`. Alembic собирает metadata через
`Base.metadata` для autogenerate миграций.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Корневой класс для всех ORM-моделей."""
