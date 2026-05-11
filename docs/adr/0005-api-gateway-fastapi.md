# ADR-0005: API Gateway на FastAPI

## Статус

- [x] **Принято**
- **Дата:** 2026-05-11
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** да, 2026-05-11 (approve Плана разработчика к Issue #3)

## Контекст

Модуль базы знаний reHome предоставляет 53 публичных endpoint'а (см. OpenAPI
`docs/handoff/01_postanovka/04_openapi.yaml`, ПЗ «API базы знаний v1.3»).
Все они проходят через единый API Gateway — единую точку аутентификации,
rate-limit'инга, логирования, CORS, доставки контента и стриминга.

Ключевые требования к технологии gateway:

- **Native async и SSE** — обязательно для AI-чата (см. ПЗ «Чат-поиск ТЗ v2»
  раздел 2.1: `POST /api/v1/chat/sessions/{id}/messages` отдаёт
  `text/event-stream`). Без native async поддержка SSE требует worker-обходов
  или wsgi→asgi shim.
- **Spec-first development** — OpenAPI v1.0 финализирован до начала кодирования.
  Желательно, чтобы фреймворк генерировал OpenAPI спецификацию из кода
  одинаково с источником истины, для автоматической верификации соответствия.
- **Производительность** — целевые latency-показатели из ПЗ «API базы знаний
  v1.3» раздел 7.1: p50 ≤ 20-200 мс для read-эндпоинтов.
- **Совместимость со стеком reHome** — Python 3.12+ (ADR-0001), Pydantic 2.x,
  Uvicorn/Hypercorn для ASGI.
- **Зрелость и экосистема** — крупный production-grade проект, активное
  сообщество, документация на русском желательна, типизация дружелюбна к
  `mypy --strict` (ТЗ 5.4).

ADR-0001 уже зафиксировал Python + FastAPI + Django в стеке. ADR-0001 не
ответил на вопрос: **кто из этих двух — gateway**. От этого решения зависят
все будущие модули, которые подключают свои routers к gateway (≥2 модуля,
по ТЗ 5.5 требуется отдельный ADR).

## Решение

API Gateway модуля kb реализуется на **FastAPI**. Конкретно:

- FastAPI ≥ 0.115 на Python 3.12+
- Uvicorn[standard] как ASGI-сервер
- Pydantic 2.x для валидации запросов/ответов и генерации OpenAPI
- Маршрутизация в gateway: `app.include_router(v1_router)` с подключением
  routers из конкретных модулей kb-* по мере их появления (E2 и далее)

Django **остаётся** в стеке для модулей, где нужны admin UI, ORM-удобства,
многолетняя экосистема пакетов (kb-wiki contentful editing, kb-staff админка,
kb-hr учёт сотрудников). Django **не** выступает в роли gateway.

## Альтернативы

1. **Django + Django REST Framework (DRF) как gateway** — отклонено:
   - Native async в Django стабилен только с 4.x в нишевых сценариях; SSE
     требует обходов (asgiref, channels). Для kb-search с долгими SSE
     ответами это узкое место.
   - DRF генерирует OpenAPI 2.0/3.0 (нет 3.1), наша спецификация на 3.1.
   - Boilerplate Serializer + ViewSet значительно больший, чем FastAPI
     Pydantic models + endpoint функции.
   - Производительность ниже из-за WSGI наследия (даже под Uvicorn workers
     async выполняется в пуле потоков).

2. **Litestar** (бывший Starlite) — отклонено:
   - Молодой проект, экосистема и количество готовых интеграций (auth,
     observability) меньше FastAPI.
   - Меньше документации на русском для будущих сотрудников.
   - Преимущества (более продвинутый DI, меньше «магии» в декораторах) не
     перевешивают риск миграции, если проект ставится на 6-12 месяцев.

3. **Sanic / Falcon** — отклонено:
   - Sanic — native async, но автогенерация OpenAPI слабее, экосистема
     уступает FastAPI.
   - Falcon — минималистичный, нет автогенерации OpenAPI без сторонних
     пакетов, не подходит для spec-first подхода.

4. **GraphQL-gateway (Strawberry / Ariadne)** — отклонено:
   - Контракт уже зафиксирован как REST + OpenAPI 3.1 (ПЗ «API базы знаний
     v1.3» раздел 1.3, ADR-0001 неявно). Менять формат — самостоятельный
     крупный пересмотр, выходящий за рамки текущей фазы.

## Последствия

### Положительные

- **Native async/await повсеместно** — SSE для чата без обходов, длинные
  upload'ы файлов (kb-files), параллельные запросы в Qdrant/Postgres в одном
  запросе (kb-search hybrid retrieval).
- **OpenAPI 3.1 автогенерация** — `app.openapi()` отдаёт схему, можно
  сравнивать с источником истины (`04_openapi.yaml`) в CI на каждом PR.
- **Pydantic 2.x** — единая модель валидации для запроса, ответа и
  внутреннего DTO. mypy strict-friendly.
- **Меньше boilerplate** — endpoint в одной функции вместо ViewSet + Serializer +
  url-конфиг (Django DRF).
- **Производительность из коробки** — gunicorn/uvicorn workers, p50 latency
  ниже Django-эквивалента в ~2-3 раза на синтетических тестах.

### Отрицательные / компромиссы

- **Команде нужно знать FastAPI** — не все Python-разработчики имеют опыт.
  Митигация: документация на русском хорошая, синтаксис близок к Flask,
  кривая обучения 1-2 недели.
- **Django всё равно нужен** для kb-wiki/kb-staff (admin UI, ORM) — два
  фреймворка в стеке, выше cognitive overhead. Митигация: чёткое разделение:
  FastAPI = gateway + async-критичные сервисы (kb-search, kb-files, kb-vault),
  Django = бизнес-логика с админкой (kb-wiki, kb-staff, kb-hr).
- **OpenAPI auto-generation FastAPI и наш источник истины** могут расходиться.
  Митигация: contract-тесты в CI (job `OpenAPI spec validation` уже в
  `.github/workflows/ci.yml` + добавится сравнение `app.openapi()` со
  spec'ом, начиная с E2 когда появятся реальные modeled endpoints).
- **Нет встроенного admin UI** для FastAPI — но gateway его и не должен
  иметь. Admin UI — в kb-staff на Django.

### Технические следствия

- В `requirements.txt` появляется `fastapi`, `uvicorn[standard]`, `pydantic`,
  `pydantic-settings`. Django добавляется отдельно в будущих модулях.
- В каждый kb-* модуль, экспонирующий endpoints, добавляется `APIRouter`,
  который импортируется в gateway `main.py` и подключается через
  `app.include_router(...)`.
- Middleware (auth, rate-limit, logging, CORS) добавляется на уровне
  gateway, не в каждом модуле.
- Тестирование — `fastapi.testclient.TestClient` (синхронный wrapper над
  httpx) или `httpx.AsyncClient(app=app)` для async-тестов.
- CI: `pytest` с `pytest-asyncio` (уже в requirements-dev.txt).

## Ссылки

- ПЗ: «API базы знаний v1.3» разделы 1.3, 2.1, 4.6 (SSE), 7.1 (latency)
- ПЗ: «Чат-поиск ТЗ v2» раздел 2.1 (gateway diagram), 2.3 (LLMProvider)
- ТЗ: «Claude Code v1.0» раздел 5.5 (когда требуется ADR)
- OpenAPI: `docs/handoff/01_postanovka/04_openapi.yaml`
- Связанные ADR: ADR-0001 (стек), ADR-0003 (двухконтурность данных —
  фильтрация на уровне хранилища)
- FastAPI docs: https://fastapi.tiangolo.com/
