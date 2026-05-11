# Архитектура модуля базы знаний reHome

> Краткий обзор. Полные ПЗ — в `docs/handoff/01_postanovka/`. Решения — в `docs/adr/`.

## Состав модуля

Модуль базы знаний состоит из 10 микросервисов / приложений:

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Пользователи и потребители                    │
│   gosti  │  tenant  │  landlord  │  agent  │  staff  │  rehome.one  │
└──────┬────────┬──────────┬───────────┬─────────┬───────────┬────────┘
       │        │          │           │         │           │
       └────────┴──────────┴───────────┴─────────┴───────────┘
                                  │
                                  ▼
                  ┌───────────────────────────────┐
                  │   kb-api-gateway (FastAPI)    │
                  │   - Auth (JWT через Keycloak) │
                  │   - Rate limiting             │
                  │   - CORS, CSP, request logs   │
                  │   - OpenAPI spec, Swagger UI  │
                  └───────────┬───────────────────┘
                              │
       ┌───────────┬──────────┼─────────┬───────────┬────────────┐
       ▼           ▼          ▼         ▼           ▼            ▼
  ┌─────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌─────────┐
  │ kb-wiki │ │kb-help │ │kb-files│ │kb-vault│ │kb-staff│ │kb-search│
  │ Django  │ │Next SSR│ │FastAPI │ │ Django │ │Next +  │ │FastAPI +│
  │         │ │        │ │+ MinIO │ │ + KMS  │ │Django  │ │ Qdrant  │
  └────┬────┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘ └────┬────┘
       │          │          │          │          │            │
       └──────────┴──────────┴──────────┴──────────┴────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
       ┌────────────┐       ┌──────────┐       ┌──────────┐
       │PostgreSQL  │       │  Redis   │       │  MinIO   │
       │+ pgvector  │       │+Dramatiq │       │   (S3)   │
       └────────────┘       └──────────┘       └──────────┘
              ▲
              │
       ┌──────┴──────┐
       │  Keycloak   │
       │   (SSO)     │
       └─────────────┘
```

### Назначение приложений

| Приложение | Назначение | Стек |
|---|---|---|
| `kb-api-gateway` | Единая точка API, auth, routing | FastAPI |
| `kb-wiki` | Внутренняя wiki сотрудников | Django + Postgres FTS |
| `kb-help` | Публичный help-центр | Next.js SSR |
| `kb-files` | Хранилище документов с подписями | FastAPI + MinIO |
| `kb-vault` | Менеджер паролей (security-critical) | Django + KMS |
| `kb-staff` | Админка реестра квартир и пользователей | Next.js + Django REST |
| `kb-hr` | Кадровый портал | Django |
| `kb-search` | RAG-движок AI-чата | FastAPI + Qdrant + LLMProvider |
| `kb-eval` | Eval-стенд для LLM | FastAPI + Postgres |
| `kb-auth` | Конфигурация Keycloak + custom claims | Keycloak realm |

## Ключевые архитектурные принципы

### 1. Разрабатываем сами, минимум внешних сервисов

Категории технологического стека:
- **A** (свой код): kb-wiki, kb-help, kb-files, kb-vault, kb-staff, kb-hr, kb-search
- **B** (open-source self-hosted): PostgreSQL, Qdrant, MinIO, Redis, Keycloak
- **C** (внешние, минимум): банк-партнёр, KYC, LLM API, SMS, ЭДО, КЭП

Подробно — ADR-0001.

### 2. Двухконтурность данных

Каждый ресурс имеет `access_level` ∈ `{PUBLIC, LOGGED, AGENT, STAFF, LEGAL, HR_RESTRICTED}`.
Фильтрация на уровне хранилища (Qdrant payload filter, Postgres WHERE).
`scope` пользователя вычисляется бэкендом из JWT, никогда не от клиента.

Подробно — ADR-0003.

### 3. Финансовая модель: два канала

- **Номинальный счёт** (ст. 860.1 ГК РФ) — арендная плата нанимателя → собственнику
- **Расчётный счёт reHome** — сервисный платёж нанимателя → платформе

Залога нет. Сервисный платёж невозвратный, при заезде.

Подробно — ADR-0002.

### 4. Единая модель коллаборантов

Сущность `Collaborator` для всех внешних организаций:
УК, ТСЖ, аварийные службы, клининг, ремонт, страховые, банк, KYC, SMS и т.д.

14 типов × 4 финансовые группы (A/B/C/D) × 3 уровня кабинета (NONE/LIGHT/FULL).

Подробно — ADR-0004.

## API контракт

Публичный API в `docs/handoff/01_postanovka/04_openapi.yaml`:
- 53 эндпоинта в v1.0
- 52 схемы данных
- REST + OpenAPI 3.1
- Две схемы безопасности: BearerAuth (m2m) и CookieAuth (browser)
- Cursor-based пагинация
- SSE для чата
- Webhooks с HMAC-подписью

См. также `docs/consumers.md` — карту потребителей.

## Безопасность

- TLS 1.3 only
- ПДн шифруются в покое (AES-256) и в передаче
- ФЗ-152: все ПДн в РФ
- audit_log для всех операций с ПДн (хранение 5 лет)
- Rate limiting по сегментам: guest / user / m2m
- MFA для критических admin-операций (переключение LLM, экспорт аудита)
- Pre-commit hook + CI scan на секреты (gitleaks)

## Деплой

- Все компоненты — на серверах в РФ
- Контейнеризация: Docker + docker-compose для dev, Kubernetes для prod
- CI/CD: GitHub Actions → staging → manual approval → prod
- Blue/green деплой для нулевого downtime
- Backup: ежедневный, шифрованный, в холодное хранилище РФ

## Roadmap

- **Phase 0** (2 нед) — инвентаризация, фундамент, mock-сервер
- **Phase 1** (3-4 мес) — MVP базы знаний
- **Phase 2** (6-10 нед) — AI-чат с RAG
- **Phase 3** (4-6 мес) — внутренний чат, коллаборанты с эскроу

## Полезные ссылки

- `docs/handoff/HANDOFF.md` — точка входа в проект
- `docs/handoff/01_postanovka/` — функциональные требования
- `docs/handoff/02_process/` — процесс разработки
- `docs/adr/` — архитектурные решения
- `docs/consumers.md` — карта потребителей API
- `docs/glossary.md` — глоссарий
- `docs/state-of-code.md` — текущее состояние кода
- OpenAPI Swagger UI: http://localhost:8000/kb/api/v1/docs (после запуска)
