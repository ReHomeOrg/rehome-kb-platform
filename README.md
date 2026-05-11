# reHome Knowledge Base — модуль базы знаний платформы reHome

> Цифровая платформа долгосрочной аренды жилья. ООО «РЕХОМ», Санкт-Петербург.

Этот репозиторий содержит модуль базы знаний reHome:
- Wiki (внутренние и публичные статьи)
- Help-центр для пользователей rehome.one
- Хранилище юридических и операционных документов
- Менеджер паролей и доступов
- Реестр карточек квартир
- Кадровый портал
- AI-чат поверх базы знаний (RAG)
- Реестр коллаборантов (УК/ТСЖ, клининг, ремонт и др.)
- API для подключения к платформе rehome.one

## Старт работы

### Если вы — Claude Code

1. Прочитайте `CLAUDE.md` (Разработчик) или `CLAUDE-REVIEWER.md` (Проверяющий).
2. Прочитайте документы постановки задачи в `docs/handoff/01_postanovka/`.
3. Изучите архитектурные решения в `docs/adr/`.
4. Следуйте процессу из `docs/handoff/02_process/`.

### Если вы — человек, впервые открывший репозиторий

1. Прочитайте `docs/handoff/HANDOFF.md`.
2. Изучите `docs/architecture.md` для понимания общей структуры.
3. Запустите локальный dev-стенд (см. ниже).

## Архитектура

Модуль базы знаний — единая платформа из нескольких приложений:

- `kb-wiki` — внутренняя wiki (Django + Postgres FTS)
- `kb-help` — публичный help-центр (Next.js SSR)
- `kb-files` — хранилище документов (FastAPI + MinIO)
- `kb-vault` — менеджер паролей (security-критичный)
- `kb-staff` — админка (Next.js + Django REST)
- `kb-hr` — кадровый портал
- `kb-search` — RAG-движок AI-чата (FastAPI + Qdrant)
- `kb-eval` — eval-стенд для LLM
- `kb-auth` — общая аутентификация (Keycloak)
- `kb-api-gateway` — единая точка API (FastAPI)

Подробности — в `docs/architecture.md` и ADR.

## Стек

**Backend:** Python 3.12+, Django 5, FastAPI, Dramatiq, PostgreSQL 16 + pgvector,
Qdrant, MinIO, Redis, Keycloak.

**Frontend:** Next.js 14+, React 18+, TypeScript strict, Tailwind CSS.

**Принцип:** «разрабатываем сами». Внешние сервисы — только критически
необходимый минимум (банк, KYC, SMS, КЭП, 1С:ЗУП, ЭДО). См. ADR-0001.

## Локальный dev-стенд

```bash
# 1. Поднять инфраструктуру
docker-compose up -d postgres redis qdrant minio keycloak

# 2. Применить миграции
make migrate

# 3. Запустить backend
make backend-dev

# 4. Запустить frontend
make frontend-dev

# 5. Запустить mock-сервер OpenAPI (для разработки rehome.one)
make mock-api
```

## Тестирование

```bash
make test              # все тесты
make test-unit         # только unit
make test-integration  # integration
make test-contract     # контрактные (по OpenAPI)
make test-e2e          # end-to-end через Playwright
make lint              # ruff + eslint + mypy + tsc
```

Покрытие тестами: ≥ 80% для бизнес-логики, ≥ 60% для UI.

## Процесс разработки

Используется двухагентная схема с участием Claude Code:

- **Агент-Разработчик** пишет код по плану.
- **Агент-Проверяющий** ревьюит и одобряет PR.
- **Архитектор** (человек) решает спорные случаи.

Полные правила — в `docs/handoff/02_process/01_ТЗ_двухагентная_разработка.docx`.

Жёсткие правила:
- Защищённые ветки (main, develop) — только через PR с approve Проверяющего.
- Никаких force-push, amend, rebase на защищённых ветках.
- Никаких костылей из списка раздела 5.2 ТЗ.
- Изменение чужого кода — только если это часть текущей задачи.
- ПДн — всегда с шифрованием, логированием, RBAC.
- access_level — фильтрация на уровне хранилища, не приложения.

## Документация

- `docs/handoff/` — пакет ТЗ от заказчика
- `docs/adr/` — Architecture Decision Records
- `docs/architecture.md` — обзор архитектуры
- `docs/glossary.md` — глоссарий проекта
- `docs/consumers.md` — карта потребителей API
- `docs/state-of-code.md` — состояние кода (артефакт Phase 0)
- `docs/phase-reviews/` — ревью каждой фазы разработки
- `CHANGELOG.md` — журнал изменений
- `OpenAPI Swagger UI` — http://localhost:8000/kb/api/v1/docs (после запуска)

## Безопасность и ФЗ-152

Платформа обрабатывает персональные данные. Соответствие ФЗ-152 — обязательное:

- Все серверы в РФ.
- Шифрование в покое (AES-256) и в передаче (TLS 1.3).
- Логирование операций с ПДн в audit_log.
- Право на удаление (`DELETE /api/v1/chat/sessions/{id}`).
- Уведомление РКН о составе данных.

При обнаружении уязвимости — security@rehome.one. Не публикуйте в публичных каналах.

## Лицензия

Proprietary. Все права принадлежат ООО «РЕХОМ».

## Контакты

- **Архитектор проекта:** <ФИО> <контакт>
- **DevOps:** <ФИО> <контакт>
- **Юрист (ФЗ-152, договоры):** <ФИО> <контакт>
