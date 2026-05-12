"""Async SQLAlchemy engine + session factory + FastAPI Depends.

Использование в endpoint'ах:
```python
from src.api.db import get_session

@router.get("/articles/{slug}")
async def get_article(slug: str, session: AsyncSession = Depends(get_session)):
    ...
```

См. ADR-0008.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.api.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Singleton AsyncEngine.

    LRU-cache на 1 значение — engine создаётся один раз на процесс.
    Параметры pool читаются из settings.
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,
    )


@lru_cache(maxsize=1)
def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        class_=AsyncSession,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — yields AsyncSession.

    Session закрывается автоматически по окончании запроса (Generator
    behavior). Commit/rollback — на стороне репозитория (для read-API
    эти операции пока не требуются).
    """
    async_session = _get_sessionmaker()
    async with async_session() as session:
        yield session
