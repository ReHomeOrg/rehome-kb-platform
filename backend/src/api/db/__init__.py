"""Database infrastructure for kb-API gateway (SQLAlchemy 2.x async).

См. ADR-0008 — обоснование выбора SQLAlchemy + Alembic + asyncpg.
"""

from src.api.db.base import Base
from src.api.db.engine import get_engine, get_session

__all__ = ["Base", "get_engine", "get_session"]
