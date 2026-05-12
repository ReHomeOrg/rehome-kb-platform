"""Integration: ChatRepository против реального Postgres (E3.1 #61).

Покрывает:
- create → append → list (end-to-end).
- CASCADE: hard-delete chat_sessions удаляет messages.
- CHECK constraint: invalid role rejected.
- session_token UNIQUE: дубликат → IntegrityError.
- Dual auth: cross-user mismatch → None.
"""

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg  # type: ignore[import-untyped]
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.chat.repository import ChatRepository

DSN = os.environ.get("DATABASE_URL", "postgresql+asyncpg://kb:kb@localhost:5432/rehome_kb")
RAW_DSN = DSN.replace("postgresql+asyncpg://", "postgresql://")


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """SQLAlchemy AsyncSession для repository тестов с auto-rollback."""
    engine = create_async_engine(DSN, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def raw_conn() -> AsyncIterator[asyncpg.Connection]:
    """Прямой asyncpg для verify-вне-транзакции и cleanup."""
    conn = await asyncpg.connect(RAW_DSN)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_append_list_e2e(db_session: AsyncSession) -> None:
    """End-to-end: создать session, добавить 2 сообщения, list возвращает оба."""
    repo = ChatRepository(db_session)
    user_id = uuid4()
    session = await repo.create_session(user_id=user_id, scope="tenant")
    await db_session.commit()

    await repo.append_message(session.id, role="user", content="hi")
    await repo.append_message(session.id, role="assistant", content="hello")
    await db_session.commit()

    messages = await repo.list_messages(session.id, user_id=user_id)
    assert len(messages) == 2
    # Order ASC (chronological)
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"

    # Cleanup
    await db_session.execute(
        __import__("sqlalchemy").text("DELETE FROM chat_sessions WHERE id = :id"),
        {"id": session.id},
    )
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cascade_delete_session_drops_messages(
    db_session: AsyncSession, raw_conn: asyncpg.Connection
) -> None:
    """Hard-delete chat_sessions → CASCADE удаляет messages."""
    repo = ChatRepository(db_session)
    user_id = uuid4()
    session = await repo.create_session(user_id=user_id, scope="tenant")
    await repo.append_message(session.id, role="user", content="hi")
    await db_session.commit()

    # Hard delete (в обход soft-delete)
    await raw_conn.execute("DELETE FROM chat_sessions WHERE id = $1", session.id)

    count = await raw_conn.fetchval(
        "SELECT count(*) FROM chat_messages WHERE session_id = $1", session.id
    )
    assert count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_invalid_role_violates_check_constraint(
    raw_conn: asyncpg.Connection,
) -> None:
    """CHECK constraint enforced на DB-уровне."""
    bad_session_id = uuid4()
    # Сначала создаём session (parent FK)
    await raw_conn.execute(
        """
        INSERT INTO chat_sessions (id, session_token, scope, expires_at)
        VALUES ($1, $2, 'guest', now() + interval '1 day')
        """,
        bad_session_id,
        uuid4(),
    )
    try:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await raw_conn.execute(
                """
                INSERT INTO chat_messages (session_id, role, content)
                VALUES ($1, 'bot', 'invalid role')
                """,
                bad_session_id,
            )
    finally:
        await raw_conn.execute("DELETE FROM chat_sessions WHERE id = $1", bad_session_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_token_unique_violation(
    raw_conn: asyncpg.Connection,
) -> None:
    """session_token UNIQUE — дубликат на INSERT → IntegrityError."""
    token = uuid4()
    id_a = uuid4()
    id_b = uuid4()
    await raw_conn.execute(
        """
        INSERT INTO chat_sessions (id, session_token, scope, expires_at)
        VALUES ($1, $2, 'guest', now() + interval '1 day')
        """,
        id_a,
        token,
    )
    try:
        with pytest.raises(asyncpg.exceptions.UniqueViolationError):
            await raw_conn.execute(
                """
                INSERT INTO chat_sessions (id, session_token, scope, expires_at)
                VALUES ($1, $2, 'guest', now() + interval '1 day')
                """,
                id_b,
                token,
            )
    finally:
        await raw_conn.execute("DELETE FROM chat_sessions WHERE id = $1", id_a)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cross_user_access_returns_none(db_session: AsyncSession) -> None:
    """ADR-0003 adaptation: wrong user_id → None (mask)."""
    repo = ChatRepository(db_session)
    owner = uuid4()
    intruder = uuid4()
    session = await repo.create_session(user_id=owner, scope="tenant")
    await db_session.commit()

    result = await repo.get_session_by_owner(session.id, user_id=intruder)
    assert result is None

    # Cleanup
    await db_session.execute(
        __import__("sqlalchemy").text("DELETE FROM chat_sessions WHERE id = :id"),
        {"id": session.id},
    )
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_token_grants_access_without_user_id(
    db_session: AsyncSession,
) -> None:
    """Anonymous flow: session_token unlocks access."""
    repo = ChatRepository(db_session)
    session = await repo.create_session(user_id=None, scope="guest")
    await db_session.commit()

    result = await repo.get_session_by_owner(session.id, session_token=session.session_token)
    assert result is not None
    assert result.id == session.id

    # Cleanup
    await db_session.execute(
        __import__("sqlalchemy").text("DELETE FROM chat_sessions WHERE id = :id"),
        {"id": session.id},
    )
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_soft_delete_filters_session_out(db_session: AsyncSession) -> None:
    """soft_delete устанавливает deleted_at; повторный get → None."""
    repo = ChatRepository(db_session)
    user_id = uuid4()
    session = await repo.create_session(user_id=user_id, scope="tenant")
    await db_session.commit()

    ok = await repo.soft_delete_session(session.id, user_id=user_id)
    assert ok is True
    await db_session.commit()

    result = await repo.get_session_by_owner(session.id, user_id=user_id)
    assert result is None

    # Idempotency: повторный delete → False (т.к. already deleted)
    ok2 = await repo.soft_delete_session(session.id, user_id=user_id)
    assert ok2 is False

    # Cleanup
    await db_session.execute(
        __import__("sqlalchemy").text("DELETE FROM chat_sessions WHERE id = :id"),
        {"id": session.id},
    )
    await db_session.commit()
