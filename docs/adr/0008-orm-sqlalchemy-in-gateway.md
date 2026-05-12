# ADR-0008: SQLAlchemy 2.x async + Alembic в API Gateway

## Статус

- [x] **Принято**
- **Дата:** 2026-05-12
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** да, 2026-05-12 (Issue #23 в фазе планирования)

## Контекст

ADR-0001 фиксирует стек: Python 3.12+, Django 5, FastAPI (для отдельных
сервисов), PostgreSQL 16. ADR-0005 фиксирует FastAPI как API Gateway
модуля kb. До этого ADR не было решения, какой **ORM** использовать
в самом FastAPI gateway:

- **Django ORM** — основной выбор для kb-wiki, kb-staff, kb-hr (где
  нужны admin UI, batteries-included)
- **SQLAlchemy** — стандарт de-facto для FastAPI
- **Raw SQL / asyncpg** — минималистичная альтернатива

E2 (Read API) — первая фаза, где gateway работает с БД. Решение
влияет на ≥2 модуля (всё, что в gateway работает с БД: Articles,
Documents, PremisesCards, ChatSessions, ServiceOrders…), требует
ADR по ТЗ 5.5.

## Решение

API Gateway модуля kb использует **SQLAlchemy 2.x async + Alembic +
asyncpg** для работы с PostgreSQL.

Конкретно:

- `sqlalchemy[asyncio]>=2.0` — ORM с native async I/O
- `asyncpg>=0.30` — async-драйвер для PostgreSQL
- `alembic>=1.14` — schema migrations (declarative + autogenerate)
- Async session factory + `Depends(get_session)` для FastAPI endpoints
- Repository pattern: вся работа с БД через классы `*Repository`, не
  напрямую `AsyncSession` в router'ах (защита от обхода фильтров
  ADR-0003 на уровне типов и code review)

Django ORM **остаётся** в стеке (ADR-0001) для **отдельных Django
приложений** kb-wiki, kb-staff, kb-hr, kb-vault — это самостоятельные
сервисы с admin UI, batteries-included, не зависящие от gateway runtime.

## Альтернативы

1. **Django ORM в gateway** — отклонено:
   - Django ORM не имеет первоклассной async-поддержки (есть `async`
     query API, но многое sync под капотом; блокирует event loop на
     части операций)
   - SSE для AI-чата (E3, ТЗ Чат-поиск 4.6) требует native async
   - gateway бы тащил Django runtime (~50 МБ) без admin UI
   - Django ORM миграции (`makemigrations`) ожидают `INSTALLED_APPS`
     контекст — overkill для gateway-only schema

2. **Raw SQL + asyncpg напрямую** — отклонено:
   - Отсутствие миграций → schema-drift между средами
   - Отсутствие типобезопасности → runtime errors на изменении схемы
   - Ручная сериализация в Pydantic → дублирование model definitions

3. **Tortoise ORM** — отклонено:
   - Молодой проект, экосистема меньше SQLAlchemy
   - Меньше production-deployment'ов, меньше доков на русском
   - Преимущества (Django-like API, async из коробки) не перевешивают
     риск зрелости

4. **SQLModel (FastAPI author)** — отклонено:
   - Wrapper над SQLAlchemy + Pydantic, новый API
   - Pydantic v2 совместимость нестабильна на момент 2026-05
   - SQLAlchemy 2.x уже даёт похожую эргономику через `Mapped[T]`

## Последствия

### Положительные

- **Native async** — event loop не блокируется на DB I/O, готово для
  SSE chat в E3
- **Pydantic 2.x совместимость** через `model_config = ConfigDict(from_attributes=True)`
- **Миграции через Alembic** — стандарт индустрии, поддержка autogenerate
- **Type-safe ORM** — `Mapped[T]` в SQLAlchemy 2.x работает с mypy strict
- **Стандарт для FastAPI-проектов** — много примеров, документации, ответы
  на Stack Overflow

### Отрицательные / компромиссы

- **Два ORM в проекте** — SQLAlchemy в gateway + Django ORM в
  kb-wiki/kb-staff/kb-hr/kb-vault. Когнитивная нагрузка для команды.
  Митигация: чёткое разделение:
  - **Gateway (this repo)** — read-API через SQLAlchemy
  - **kb-wiki/kb-staff/kb-hr/kb-vault** (будущие отдельные сервисы) —
    admin UI через Django, пишут/читают через **API gateway**, не
    напрямую через Django ORM в общую БД
- **Alembic env.py** требует ручной настройки для async (стандартный
  `run_sync` pattern, есть в SQLAlchemy docs)
- **Schema ownership** — gateway-Alembic управляет схемой articles,
  documents, chat_sessions, etc. Django apps НЕ создают свои миграции
  на эти таблицы; они только пишут/читают через gateway API.

### Технические следствия

- Новый каталог `backend/src/api/db/` (engine, session, base)
- Новый каталог `backend/alembic/` (config, env, versions)
- В каждом домене (`backend/src/api/articles/`,
  `backend/src/api/documents/`, …) — `models.py` (SQLAlchemy),
  `schemas.py` (Pydantic), `repository.py`
- `Depends(get_session)` + `Depends(repository_factory)` —
  стандартный паттерн в endpoints
- **Repository pattern обязателен** — router'ы НЕ принимают
  `AsyncSession` напрямую, только `*Repository`. Это защита от
  обхода ADR-0003 фильтров (нельзя случайно написать
  `await session.execute(select(Article))` без access_level filter)
- В Production (Phase 2) — connection pool tuning, read-replicas,
  pgvector extension через миграции

## Ссылки

- Issue: https://github.com/rehome-one/rehome-kb-platform/issues/23
- ADR-0001 (стек), ADR-0003 (двухконтурность, storage-level filter),
  ADR-0005 (FastAPI gateway), ADR-0006 (slug as identifier)
- ПЗ: «API базы знаний v1.3» раздел 10.2 E2 (Read API)
- Внешние:
  - [SQLAlchemy 2.0 async docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
  - [Alembic async setup](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic)
  - [FastAPI SQL docs](https://fastapi.tiangolo.com/tutorial/sql-databases/)
