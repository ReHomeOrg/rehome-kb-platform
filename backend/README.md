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

## Структура

```
backend/
├── src/api/
│   ├── main.py        — FastAPI app instance
│   ├── config.py      — pydantic Settings (env-driven)
│   └── v1/
│       ├── router.py  — APIRouter("/api/v1") + include subrouters
│       └── health.py  — GET /health, GET /version
└── tests/unit/
    └── test_health.py
```
