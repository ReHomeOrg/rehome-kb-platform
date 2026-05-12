# reHome KB API gateway

API Gateway модуля базы знаний reHome — единая точка входа для всех 53 endpoints,
определённых в `docs/handoff/01_postanovka/04_openapi.yaml`.

Стек: Python 3.12+, FastAPI, Uvicorn, Pydantic 2.x (см. ADR-0001, ADR-0005).

## Запуск

```bash
make install        # python deps в текущий venv
make run            # uvicorn на :8000, --reload
```

Затем:
- `GET http://localhost:8000/api/v1/health` → `{"status": "ok"}`
- `GET http://localhost:8000/api/v1/version` → метаданные сборки
- `GET http://localhost:8000/docs` → Swagger UI (FastAPI default)

## Проверки

```bash
make lint           # ruff check + format check
make typecheck      # mypy --strict
make test           # pytest
make test-cov       # pytest + coverage (порог 80%)
```

## Переменные окружения

| Имя | Значение по умолчанию | Назначение |
|---|---|---|
| `REHOME_API_VERSION` | `1.0.0-alpha` | Версия API, в ответе `/version` |
| `GIT_COMMIT` | `unknown` | SHA коммита, проставляется CI |
| `BUILD_DATE` | `unknown` | Дата сборки (ISO 8601), проставляется CI |
| `REHOME_ENV` | `dev` | Окружение: `prod` / `staging` / `dev` / `local` |
| `KC_URL` | `http://localhost:8080` | Keycloak base URL (см. infra/keycloak/) |
| `KC_REALM` | `rehome` | Keycloak realm name (см. ADR-0007) |
| `KC_AUDIENCE` | `account` | Ожидаемое значение `aud` claim |
| `KC_VERIFY_AUD` | `false` | Проверка audience (на E1.3.2 отключена; будет true после E1.3.4) |
| `DATABASE_URL` | `postgresql+asyncpg://kb:kb@localhost:5432/rehome_kb` | PostgreSQL для articles/... (ADR-0008) |

## База данных

PostgreSQL 16 + SQLAlchemy 2.x async + Alembic (см. ADR-0008).

```bash
# Запуск local-dev БД
cd ../infra && docker compose up -d postgres-kb

# Прогон миграций
cd ../backend && make migrate

# Создать новую миграцию из изменений моделей
make migrate-create m="add foo column"

# Откатить последнюю миграцию
make migrate-downgrade
```

Все ORM-модели должны быть импортированы в `src/api/db/models_all.py`,
иначе Alembic autogenerate их не увидит. Repository pattern обязателен —
router'ы НЕ ходят в `AsyncSession` напрямую (ADR-0008).

## Auth

OIDC middleware валидирует JWT через JWKS endpoint Keycloak. Подробности —
ADR-0007.

- **Endpoint `GET /api/v1/whoami`** — диагностический, возвращает `scope`,
  `roles` и `access_levels` текущего пользователя по предъявленному токену.
  Без токена → анонимный `guest`.
- **`require_access_level(level)`** — FastAPI `Depends`-factory для защиты
  endpoint'ов: 403 если у пользователя нет требуемого `AccessLevel`.
- **`scope` НИКОГДА не принимается от клиента** (ADR-0003). Любая попытка
  передать `?scope=...`, `X-Scope` header, или поле в body — игнорируется.

См. также `src/api/auth/scope.py` — `SCOPE_TO_ACCESS_LEVELS` — единственный
источник истины для соответствия Scope → AccessLevel (синхронно с ADR-0003).

## Структура

```
backend/
├── alembic/             — SQL migrations (ADR-0008)
│   ├── env.py
│   └── versions/
├── alembic.ini
├── src/api/
│   ├── main.py          — FastAPI app instance
│   ├── config.py        — pydantic Settings (env-driven)
│   ├── db/              — async engine, sessionmaker, get_session
│   │   ├── base.py      — DeclarativeBase
│   │   ├── engine.py    — get_engine, get_session (FastAPI Depends)
│   │   └── models_all.py — единая точка импорта моделей для Alembic
│   ├── articles/        — ADR-0003: storage-level access_level filter
│   │   ├── models.py    — Article ORM
│   │   ├── repository.py — read-операции с обязательным WHERE access_level
│   │   ├── router.py    — GET /articles/{slug}
│   │   └── schemas.py   — Pydantic v2 ArticleResponse
│   ├── auth/            — OIDC verifier, scope/access_level
│   └── v1/
│       ├── router.py    — APIRouter("/api/v1") + include subrouters
│       └── health.py    — GET /health, GET /version
└── tests/
    ├── unit/            — pytest unit-тесты с моками
    └── integration/     — end-to-end с реальным Keycloak + Postgres
```
