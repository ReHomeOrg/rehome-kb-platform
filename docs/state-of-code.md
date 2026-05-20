# State of Code Report

> Артефакт Phase 0 — инвентаризация существующего кода reHome.
> Базовая точка отсчёта (baseline) для всей последующей разработки по ТЗ Claude Code v1.0 раздел 7.1.

**Статус:** ✅ Утверждено
**Дата:** 2026-05-11
**Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
**Утверждено Архитектором:** 2026-05-11 (подтверждение в чате при approve Плана разработчика к Issue #1)

> **TL;DR:** Проект — **greenfield**. Существующего кода reHome нет (подтверждено Архитектором). Репозиторий `rehome-one/rehome-kb-platform` создан 2026-05-11 и содержит только handoff-документы и шаблоны процесса. Phase 1 начинается с E1 (Foundation) по ПЗ «API базы знаний v1.3» раздел 10.2.

---

## 1. Структура репозиториев

На момент составления baseline существует **один** репозиторий проекта:

| Репозиторий | URL | Описание | Стек |
|---|---|---|---|
| `rehome-one/rehome-kb-platform` | https://github.com/rehome-one/rehome-kb-platform | Монорепо модуля базы знаний reHome (kb-*) | пока пусто (только handoff + процессные файлы) |

GitHub organization `rehome-one` (Free plan) создан 2026-05-11 как контейнер под все будущие репозитории проекта (см. раздел 10 ниже).

Альтернатива «несколько репозиториев под каждый kb-* модуль» — отвергнута на этой итерации: монорепо упрощает работу одной команды, общий CI, синхронные релизы. Решение пересмотрит ADR на этапе E3 или E4, если объём кода превысит ~50k строк.

### 1.1. Текущий состав файлов (commit `1d01460`)

```
.
├── CLAUDE.md                              ← операционная инструкция Разработчика
├── CLAUDE-REVIEWER.md                     ← операционная инструкция Проверяющего
├── README.md                              ← точка входа
├── .github/
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── ISSUE_TEMPLATE/{adr-request,bug,task}.md
│   └── workflows/ci.yml                   ← CI: lint+типы+тесты+OpenAPI+security
└── docs/
    ├── architecture.md                    ← обзор архитектуры (общее)
    ├── state-of-code.md                   ← этот файл
    ├── adr/
    │   ├── README.md
    │   ├── 0000-template.md
    │   ├── 0001-platform-architecture.md  ← стек, категории A/B/C
    │   ├── 0002-financial-model.md        ← сервисный платёж, два канала
    │   ├── 0003-knowledge-base-tiers.md   ← двухконтурность
    │   └── 0004-collaborators-model.md    ← 14 типов × 4 группы × 3 уровня кабинета
    └── handoff/
        ├── HANDOFF.md, INDEX.md
        ├── 01_postanovka/    ← ПЗ: что строим (4 документа + OpenAPI 3.1)
        ├── 02_process/       ← ТЗ: как строим (двухагентная схема)
        └── 04_supporting/    ← Договор, оферта, ФЗ-152, flow, investor deck
```

Всего 36 файлов, 14259 строк (markdown + YAML + один PDF).

## 2. Технологический стек (фактический на момент начала)

**Greenfield — ничего не установлено и не запущено.** Ниже — целевой стек по ADR-0001, со статусом «не подключено» для каждого пункта.

### Backend (категория A — разрабатываем сами; категория B — open-source self-hosted)

| Компонент | Целевое | Фактическое |
|---|---|---|
| Python | 3.12+ | ❌ не установлен |
| Django | 5.x | ❌ |
| FastAPI | latest (для kb-search, kb-files, kb-vault) | ❌ |
| Dramatiq | для очередей | ❌ |
| PostgreSQL | 16+ (с pgvector) | ❌ |
| Qdrant | для kb-search RAG | ❌ |
| MinIO | S3-совместимое хранилище | ❌ |
| Redis | очередь + кеш | ❌ |
| Keycloak | self-hosted SSO | ❌ |

### Frontend

| Компонент | Целевое | Фактическое |
|---|---|---|
| Next.js | 14+ (App Router) | ❌ |
| React | 18+ | ❌ |
| TypeScript | strict mode | ❌ |
| Tailwind CSS | latest | ❌ |

### Инфраструктура

| Компонент | Целевое | Фактическое |
|---|---|---|
| Серверы | РФ: Yandex Cloud / Selectel | ❌ ни одного серверa нет |
| Контейнеризация | Docker | ❌ |
| Оркестрация | TBD (на E1 решим: docker-compose для dev, k8s или nomad для prod — отдельный ADR) | ❌ |
| CI/CD | GitHub Actions (`.github/workflows/ci.yml` уже добавлен в репо) | ⚠️ файл есть; до коммита `dbc73c5` все прогоны давали 0 jobs из-за YAML parse error (шаг `No except: pass` с неэкранированным двоеточием — главная причина). После фикса в `dbc73c5` стало видно вторичную причину — отсутствие `requirements.txt`/`package.json` в корне. Backend (Python) job стал зелёным после E1.1 (PR #4). Остальные jobs (frontend, security, openapi) — закрываются в E1.2 и follow-up Issues |
| Наблюдаемость | Prometheus + Grafana + Loki | ❌ |
| Sentry | для ошибок (опционально) | ❌ |

### Внешние сервисы (категория C по ADR-0001)

| Сервис | Назначение | DPA | Контракт |
|---|---|---|---|
| Точка / Т-банк | Расчётный счёт, эквайринг, номинальный счёт | ❌ | ❌ |
| Cyclops | KYC по 115-ФЗ | ❌ | ❌ |
| LLM API (YandexGPT / GigaChat) | Генерация ответов в чате | ❌ | ❌ |
| Embeddings API | Векторизация контента (на старте — внешний, затем self-hosted) | ❌ | ❌ |
| Exolve | SMS-OTP | ❌ | ❌ |
| Контур.Диадок | КЭДО | ❌ | ❌ |
| 1С:ЗУП | Расчёт зарплаты, отчётность | ❌ | ❌ |
| Облачная касса (АТОЛ/Эвотор) | 54-ФЗ фискализация | ❌ | ❌ |
| Dadata / Контур.Фокус | Справочники, проверка контрагентов | ❌ | ❌ |
| УЦ Контур | КЭП-токен | ❌ | ❌ |

## 3. Тестовое покрытие (baseline)

**0%** — ни одного теста (нет кода).

**Целевые значения** (ТЗ раздел 5.4 и 8.3):
- Бизнес-логика: **≥ 80%** (блок merge при < 60%)
- UI-компоненты: **≥ 60%** (блок merge при < 40%)
- Security-критичный код (KYC, платежи, `access_level`): отдельные тесты на попытки обхода прав — **обязательно**

## 4. Существующие сущности и модели данных

**Никаких** — greenfield. Целевые сущности зафиксированы в:
- ПЗ «База знаний v1.4» раздел 9.1 (User, Lead, Premises, Booking, Payment, AcceptanceAct, CyclopsBeneficiary, OwnerVerification, CounterpartyCheck, OnboardToken, LeadInteractionLog, Dispute, InsurancePolicy, PartnerService, ServiceOrder, FinancialLedger)
- ПЗ «База знаний v1.4» раздел 10 + ADR-0004 (Collaborator, PremisesCollaborator, ServiceOrder, CollaboratorReview)
- OpenAPI `docs/handoff/01_postanovka/04_openapi.yaml` — машиночитаемая спецификация всех schemas (Article, Document, PremisesCard, FinancialBlock, ChatSession, ChatMessage, SearchHit, Webhook, KbUser, AuditLogEntry и др.)

Все модели реализуются с нуля в рамках Phase 1.

## 5. Известные баги и техдолг

Баги существующего кода — **нет** (нет кода).

**Архитектурный долг и риски на старте:**

| ID | Описание | Severity | Влияние на разработку |
|---|---|---|---|
| TD-001 | Отсутствие технической защиты веток `main` (отступление от ТЗ раздел 6.4 по решению Архитектора 2026-05-11 из-за тарифа GitHub Free) | P2 | GitHub не блокирует прямой push в `main`. Двухагентная дисциплина держится на CLAUDE.md/CLAUDE-REVIEWER.md. Каждый PR Разработчик создаёт через ветку и явный PR, не amend/rebase в `main` |
| TD-002 | ~~Проверяющий как отдельная Claude-сессия пока не поднят~~ **Закрыт 2026-05-11** post-hoc аудитом PR #2 и PR #4 (Claude Code agent id `a4be970c66aac34ba`). С Issue #5 двухагентный цикл работает в полном объёме | ~~P1~~ closed | ~~Approve и merge временно делает Архитектор~~ С Issue #5 approve плана и merge PR выполняет Проверяющий (отдельный Claude-контекст) |
| TD-003 | CI давал 0 jobs / 0 check-runs с bootstrap'а (`1d01460`) до `dbc73c5`. **Главная причина** — YAML parse error в `.github/workflows/ci.yml` (шаг `No except: pass` с неэкранированным двоеточием, исправлено в `dbc73c5`). **Вторичная причина** — отсутствие `requirements.txt`/`package.json` в корне (закрылось для backend в PR #4 через `working-directory: backend`). Frontend/security/openapi jobs всё ещё красные — закрываются в E1.2 и follow-up Issues | P2 | На bootstrap фактически блокировал любую CI-проверку. Сейчас Backend (Python) и Anti-crutches зелёные. Не блокирует docs-only PRs |
| TD-004 | Юридические правки договора найма и публичной оферты — deferred Архитектором | P1 | Блокер выкатки MVP, но не блокер начала разработки. Возвращаемся к вопросу за 4-6 недель до запуска E3/E4 |
| TD-005 | Размер сервисного платежа (фикс vs %, НДС) — deferred Архитектором | P1 | В платёжном коде использовать config-driven значения с TODO, не хардкод. Решение нужно к моменту реализации платёжного контура (E1.5 или E2) |
| TD-006 | Состав 3-5 коллаборантов MVP не определён | P2 | Не блокер до начала E7 (Collaborators). До этого момента — Архитектор подтвердит выборку |
| TD-007 | Канал и SLA эскалаций к Архитектору формально не зафиксированы | P3 | На данный момент канал = чат Claude Code. Достаточно для одной активной задачи; формализуем при подключении второй Claude-сессии (Проверяющего) |

## 6. Внешние зависимости (категория C по ADR-0001)

См. раздел 2 выше — таблица «Внешние сервисы». По состоянию на 2026-05-11 ни один сервис категории C не подключён, ни одного DPA не подписано.

## 7. Соответствие ФЗ-152 (текущее состояние)

| Требование | Состояние | Замечания |
|---|---|---|
| Шифрование ПДн в покое (AES-256) | ⏳ PENDING | Нет данных и нет БД |
| Шифрование в передаче (TLS 1.3) | ⏳ PENDING | Нет деплоя |
| `audit_log` для операций с ПДн | ⏳ PENDING | Реализуется в E6 (Admin → audit-log) |
| Серверы в РФ | ⏳ PENDING | Не выбран провайдер. Целевое: Yandex Cloud / Selectel (см. ADR-0001) |
| Уведомление в Роскомнадзор подано | ❌ NOT STARTED | Юр.задача, не разработческая. Срок — до начала обработки ПДн (до E3) |
| Политика обработки ПДн опубликована | ❌ NOT STARTED | Документ существует в `docs/handoff/04_supporting/02_Публичная_оферта_исходник.md`, но требует юр.правок (см. TD-004) |
| Согласия пользователей собираются | ❌ NOT STARTED | 4 отдельных согласия по ПЗ «База знаний v1.4» раздел 4.2.2. Реализуется в E1 (Foundation → auth) |
| Регламент реагирования на инциденты (24/72 ч) | ❌ NOT STARTED | Документ-регламент REG-PD-02 — задача контент/юр.команды, реализация системы алертов — в E6 |
| Маскировка ПДн перед передачей в LLM | ⏳ PENDING | Реализуется в E3 (kb-search RAG pre-processor) |
| Назначение ответственного за обработку ПДн | ❌ NOT STARTED | Организационное действие — приказ в ООО «РЕХОМ» |
| Обучение сотрудников по ПДн | ❌ NOT STARTED | HR-процедура |
| DPA с внешними сервисами категории C | ❌ NOT STARTED | По мере подключения каждого сервиса |

**Итого:** соответствие ФЗ-152 на момент baseline = **0%**. Это ожидаемо для greenfield, но фиксируется явно: каждая задача E1-E7 должна закрывать конкретные пункты этого чек-листа, и финальный аудит ФЗ-152 — обязательное условие готовности MVP.

## 8. Что НЕТ в существующем коде (отсутствующее)

Всё перечисленное в ADR-0001 категория A — отсутствует, реализуется с нуля в Phase 1:

- ❌ `kb-wiki` — внутренняя wiki базы знаний (Django + Postgres FTS)
- ❌ `kb-help` — публичный help-центр (Next.js SSR)
- ❌ `kb-files` — хранилище документов (FastAPI + MinIO)
- ❌ `kb-vault` — менеджер паролей (security-критичный, отдельный сервис)
- ❌ `kb-staff` — админка реестра квартир и пользователей (Next.js + Django REST)
- ❌ `kb-hr` — кадровый портал
- ❌ `kb-search` — RAG-движок для AI-чата (FastAPI + Qdrant + LLMProvider абстракция)
- ❌ `kb-eval` — стенд экспериментов с LLM-провайдерами
- ❌ `kb-auth` — единый SSO через Keycloak
- ❌ `kb-infra` — общие миграции, деплой, observability

Дополнительно отсутствует:
- ❌ Реализация 53 эндпоинтов из OpenAPI v1.0 (мок-сервер из спецификации можно поднять командой `npx @stoplight/prism-cli mock docs/handoff/01_postanovka/04_openapi.yaml --port 8080` — это запасной вариант для интеграции потребителей до готовности backend)
- ❌ TypeScript SDK для rehome.one (генерируется из OpenAPI через `npx openapi-typescript ...`)
- ❌ Второй Claude-агент (Проверяющий) как отдельная сессия (TD-002)

## 9. Что МОЖНО переиспользовать

**Ничего** (greenfield, подтверждено Архитектором 2026-05-11).

Из соседних проектов / экосистемы reHome — нет известных репозиториев, к которым у проекта kb есть доступ или с которыми требуется интегрироваться по коду на момент baseline. Будущая интеграция с платформой rehome.one — только через публичный API kb-модуля (см. ПЗ «API базы знаний v1.3»).

## 10. Рекомендации к старту Phase 1

Порядок этапов и оценки фиксированы в **ПЗ «API базы знаний v1.3» раздел 10.2** (E1-E7, итого ~22 недели). Детальный план Phase 1 опубликован отдельным комментарием в Issue #1 (см. критерий приёмки №2).

Краткие рекомендации к запуску:

1. **Начать с E1 — Foundation (2 недели).** Цель: «всё горит зелёным на пустом коде». Включает:
   - Установка `requirements.txt`/`package.json` чтобы CI стал зелёным (TD-003).
   - Подъём Keycloak self-hosted (test instance).
   - Базовая структура backend (Django project) и frontend (Next.js).
   - Реализация Health/Version/OpenAPI docs endpoints (минимум 3 эндпоинта из 53).
   - Mock-сервер из OpenAPI — параллельно для интеграции rehome.one с первой недели.
2. **Параллельно с E1** — поднять вторую Claude-сессию как Проверяющего (TD-002), чтобы со второй задачи Phase 1 заработал двухагентный цикл.
3. **На границе E1/E2** — формальная встреча по deferred-вопросам (TD-004, TD-005, TD-006) и принятие решений по ним до начала E3 (Chat MVP), где они станут блокерами.
4. **Регулярная сверка с OpenAPI.** Любое отклонение реализованного эндпоинта от `04_openapi.yaml` блокирует merge через contract-test в CI (job `openapi`).
5. **ФЗ-152 в каждом PR.** Раздел 7 этого отчёта должен в течение Phase 1 двигаться от 0% к 100% по мере прохождения эпиков. Архитектор отслеживает прогресс при ревью каждого Issue.

---

## Утверждение

- [x] Разработчик прочитал и согласен с описанием — Agent (Claude Code), 2026-05-11
- [x] Проверяющий прочитал, замечаний нет — Claude Code agent (id `a4be970c66aac34ba`), 2026-05-11, post-hoc audit PR #2 и PR #4
- [x] Архитектор утвердил отчёт как baseline — Evgeniy, 2026-05-11

**Подписи (дата):**
- Разработчик: Claude Code (Opus 4.7), 2026-05-11
- Проверяющий: Claude Code agent (id `a4be970c66aac34ba`), 2026-05-11, post-hoc audit PR #2 и PR #4
- Архитектор: Evgeniy, 2026-05-11

После утверждения State of Code Report становится baseline. Изменения в нём требуют отдельного ADR (раздел 2.4 ТЗ).

---

# Current State (2026-05-18)

> Snapshot текущего состояния кодовой базы. Phase 0 baseline выше остаётся
> историческим артефактом — здесь актуальный inventory для онбординга
> новых участников и audit'а покрытия ТЗ.

**Статус Phase 1:** ✅ Foundation closed, эпики E2-E7 в активной фазе. Большинство модулей foundation-ready или MVP-complete.

**Метрики проекта:**
- Backend: 143 Python модуля, 136 test files, **1304+ unit tests passing** (mypy strict ✓, ruff ✓).
- Frontend: **486 Vitest tests** в 83 файлах (Next.js 14 App Router + TypeScript strict).
- 22+ Alembic миграций (через 0023).
- 335+ commits since baseline (2026-05-11).
- 17 ADRs (0001-0017), все принятые.

## CS.1. Backend модули

| Модуль | Статус | Кратко |
|---|---|---|
| `articles` | ✅ MVP | CRUD + версионирование + Postgres FTS поиск + tags + categories + frontend admin форма |
| `audit` | ✅ MVP | Centralized audit_log table + repository + viewer page |
| `auth` | ✅ MVP | Keycloak JWT verify + scope mapper (ADR-0003 access_levels) + roles/scopes endpoint |
| `categories` | ✅ MVP | Иерархия + counts |
| `chat` | ✅ MVP | Sessions + SSE streaming + escalation + 4 LLM providers (mock, vLLM, GigaChat, YandexGPT) |
| `collaborators` | ✅ Epic | Slices 1-6: CRUD, lifecycle, public onboarding form, portal access, reviews, metrics, premises junction (PR #226-#246) |
| `documents` | ✅ MVP | MinIO upload + signed URL + audit + frontend upload UI |
| `hr` | ✅ MVP | Employee CRUD + frontend create/edit/archive (Stage 1 — ПДн encryption deferred) |
| `idempotency` | ✅ Foundation | Idempotency-Key header support for POST endpoints |
| `observability` | ✅ Foundation | Prometheus middleware + /metrics endpoint + readiness probe |
| `premises` | ✅ MVP | Per-scope projection + CRUD + tenant info + collaborators junction UI |
| `search` (kb-search) | ✅ Stage 1 | Hybrid retrieval (pgvector + BM25 + RRF) + HF embedding provider + cross-encoder rerank (PR #261-#262) |
| `tags` | ✅ MVP | List with counts |
| `vault` | ✅ MVP closed | 9 PRs: zero-knowledge crypto, groups, sharing (multi-user wraps per ADR-0017), TOTP 2FA, rotation reminders. Frontend Slices 1-5 (PR #248-#256) |
| `webhooks` | ✅ MVP | Outbound HMAC-signed delivery с retries + UI |
| `eval` (kb-eval) | ✅ MVP | LLMJudge unlocked (4 metrics via Likert 1..5 → composite), 45 golden Q&A pairs across 9 categories, CLI с поддержкой всех 4 LLM providers |

## CS.2. Frontend модули

| Route | Статус | Использует |
|---|---|---|
| `/admin/*` | Admin panel | Collaborators (queue, lifecycle, portal-access, junction), HR, Audit, Articles |
| `/articles` | Public + edit | Search, list, detail с markdown, create/edit/delete (STAFF+) |
| `/categories` | Public | Tree view |
| `/chat` | Auth | Sessions list + SSE chat + citations + escalation + feedback |
| `/documents` | Auth+ | List/detail/upload (MinIO) |
| `/hr` | HR_RESTRICTED | List/detail/edit/archive |
| `/premises` | Mixed scope | List, search, detail с per-scope projection, edit (STAFF+), collaborators section |
| `/onboarding/collaborator` | Public | Anonymous landing form для self-service (ADR-0015) |
| `/vault` | Auth | Zero-knowledge UI: setup, unlock c TOTP, secrets CRUD, groups, share, rotation banner |
| `/tags`, `/webhooks`, `/login` | Auxiliary | List + management |

## CS.3. ADR Index

| # | Заголовок | Резюме |
|---|---|---|
| 0001 | Platform architecture | Стек: FastAPI + Next.js + Postgres + Keycloak + MinIO |
| 0002 | Financial model | Сервисный платёж (расчётный счёт) + номинальный счёт для аренды + 7% комиссия |
| 0003 | Knowledge base tiers | Двухконтурный access_level: PUBLIC/LOGGED/AGENT vs STAFF/LEGAL/HR_RESTRICTED |
| 0004 | Collaborators model | 14 типов × 4 финансовых группы × 3 portal_access уровня |
| 0005 | API gateway FastAPI | Async-first; alembic migrations; pydantic-settings |
| 0006 | Slug as canonical | Articles identified slug'ом (URL-friendly) |
| 0007 | Keycloak realm | Realm 'rehome', m2m + spa clients, audience mapper |
| 0008 | ORM SQLAlchemy | Async ORM + asyncpg driver |
| 0009 | Secrets management | SOPS + age + secrets/ dir convention |
| 0010 | RAG kb-search | Hybrid pgvector + BM25 + RRF; HF embeddings; rerank (follow-up #261); Qdrant — Stage 2 |
| 0011 | Vault architecture | Zero-knowledge E2EE: Argon2id + AES-GCM + X25519 sealed-box |
| 0012 | Documents object storage | MinIO S3-compatible с signed URLs |
| 0013 | Eval-stand LLM providers | Composite score formula: 0.4·correctness + 0.3·faithfulness + 0.2·citation + 0.1·refusal |
| 0014 | Collaborators foundation | Scope-aware visibility + 404 mask + Slice planning |
| 0015 | Collaborators onboarding | Public form + portal_access tier flow + rate limit |
| 0016 | Vault frontend crypto | hash-wasm (Argon2id) + @noble/curves (X25519) + WebCrypto stack |
| 0017 | Vault sharing | Multi-user wraps (supersedes 0011 §«Group keypair») |

## CS.4. Тех-долг и backlog

**Production blockers (важные):**
- Real RU LLM credentials — GigaChat / YandexGPT настроены в коде, требуют ops setup для production deployment.
- Russian Trusted CA bundle для GigaChat TLS (ops task).
- 200-pair golden dataset (сейчас 45 baseline; content team дозаполнить).
- LLMJudge validation: 50 manual pairs vs auto ≥80% agreement (content task per ADR-0013 §4).

**Backlog по модулям:**
- **HR Stage 2**: ПДн encryption (паспорт, ИНН, СНИЛС, банк), 1С:ЗУП интеграция, КЭДО.
- **Vault Stage 2**: FIDO2 hardware token, emergency access (2-of-2 escrow), true revoke (rotate secret_key + re-wrap), QR-код для TOTP setup, batch pubkey endpoint для groups >50.
- **kb-search Stage 2**: Qdrant migration при scale; вынос embedding в shared worker через Lifespan.
- **kb-eval**: smoke run в CI с real provider'ом (требует credentials); composite score baseline measurement и dashboard.
- **Observability**: Grafana dashboards для каждого hot path; alert rules.
- **Documentation**: OpenAPI spec drift sync (некоторые operationId'ы помечены `planned` хотя уже реализованы).

## CS.5. CI / CD

**8 CI jobs** в `.github/workflows/ci.yml`:
1. **Backend (Python)**: ruff lint+format, mypy strict, pytest+coverage, Docker build smoke.
2. **Frontend (Next.js)**: ESLint, tsc strict, Vitest, build, Docker smoke.
3. **E2E (Playwright smoke)**: backend-less smoke (login, 404).
4. **OpenAPI spec validation**: Redocly lint.
5. **Anti-crutches checks**: detects TODO/HACK/FIXME без issue references.
6. **Security scan**: dependency vulnerability + secrets leak.
7. **Integration (Keycloak)**: realm import + JWT verify smoke.
8. **RAG smoke (HF embeddings + eval CLI)**: installs sentence-transformers MiniLM, прогоняет HF tests + eval CLI smoke против 45-пары dataset'а (PR #260).

## CS.6. Историческая справка

Phase 0 baseline (выше) — артефакт момента запуска проекта 2026-05-11. С тех пор:
- Завершён E1 Foundation, E2 Articles, E3 Chat MVP + LLM providers, E4 Articles management, E5 Webhooks + idempotency.
- Vault MVP полностью закрыт (E6 эквивалент).
- kb-search Stage 1 (hybrid retrieval + rerank).
- kb-eval MVP с LLMJudge.
- Все frontend admin pages для основных модулей.

Phase 0 раздел «Что МОЖНО переиспользовать» = «ничего, greenfield» уже не релевантен — теперь reuse — это existing internal modules через FastAPI dependency injection (pattern зафиксирован в ADR-0005/0008).

---

# Current State (2026-05-22)

> Refresh после landing'а webhook taxonomy completion, admin endpoints
> foundation, новых ФЗ-152 модулей и HR Stage 2 encryption proposal.

**Метрики проекта (delta vs 2026-05-18):**
- Backend: **1338 unit tests passing** (+ ~30 since 2026-05-18), mypy strict ✓, ruff ✓.
- 24+ Alembic миграций (через 0024_*).
- **18 ADRs** (0001-0018; ADR-0018 — HR ПДн encryption, accepted 2026-05-22).
- 0 open PR'ов; 55 merged 2026-05-22..23; OpenAPI 97/97 (см. CS.7).

## CS.7. Recent PRs (2026-05-23 finale)

55 PR'ов merged между 2026-05-22 и 2026-05-23. Текущее состояние:
**0 открытых PR'ов**. OpenAPI **97/97 endpoints** (100%) реализованы.

Daytime batch (16 PR'ов):
- Webhook emitters (#220-#225): popular_query, article.updated,
  premises_card.updated, chat.no_answer, audit.security_event,
  7 collaborator.* events.
- Service Orders (#224, #270): lifecycle MVP (created, cancelled).
- Premises financial endpoint (#226, #272).
- KB users CRUD (#230, #276).
- HR PII encryption Stage 2 (#234, #279) per ADR-0018.
- Admin chain: stats (#227/#273), llm/providers (#228/#274),
  system-config (#229/#275), security_incidents CRUD (#231/#277),
  personal_data_requests CRUD (#232/#278).
- Alembic merge revisions (#284, #285) — multi-head fixes.

Evening batch (14 PR'ов):
- GET /admin/audit-log alias (#237/#287) — OpenAPI-compliant param
  names над существующим /audit-log.
- OpenAPI drift sync (#288) — 58 endpoints marked as implemented.
- Operational triad (#238/#289) — DELETE /admin/cache + POST
  /admin/reindex + GET /admin/tasks/{id} + admin_tasks foundation.
- POST /admin/audit-log/export (#239/#290) — admin_tasks-backed
  task с result_url → existing /audit-log/export.csv.
- State-of-code refreshes (#286, #291, #294).
- Real reindex implementation (#240/#292) — replaces #238 honest stub;
  ArticleRepository.iter_published_for_reindex + IndexerService
  .reindex_all_articles + sync execution в request.
- Prometheus alert rules + observability docs (#241/#293) — 14 alerts
  across 8 groups; catalog of 30 backend metrics.
- Real documents alerts (#242/#295) — fixed placeholder из #293
  (outcome label уже существует).
- Coverage для iter_published_for_reindex (#243/#296) — 4 tests
  закрывают gap из #240.
- POST/GET /admin/llm/eval-runs (#244/#297) — closes 2 of 4 remaining
  unimplemented OpenAPI admin endpoints. MVP per ADR-0013: mock +
  smoke only; aggregate results inline в admin_task.params.

Late-night batch (10 PR'ов, в основном frontend):
- MockJudge integration в eval-runs (#246/#299) — populates
  answer_correctness / refusal_correctness в response.
- ADR-0019 Proposed (#247/#300) — writable runtime config storage
  design для PATCH /admin/system-config + PUT /admin/llm/active
  (последние 2 unimplemented endpoints); awaiting architect approve.
- /admin/eval-runs frontend page (#248/#301) — read-only list +
  per-provider metrics таблица.
- /admin/security-incidents UI (#249/#302) — ФЗ-152 §17.1 admin UI;
  filter + РКН pending warning banner.
- /admin/personal-data UI (#250/#303) — ФЗ-152 §15 SAR review;
  OVERDUE highlight + active/overdue counters.
- /admin dashboard (#251/#304) — landing page с 4 stat panels
  (content / chat / security / misc) + cross-links на sub-pages.
- /admin/llm-providers + /admin/system-config (#252/#305) — read-only
  info pages.
- /admin/users (#253/#306) — KB staff users list с MFA warning +
  cross-link добавление на dashboard.
- Nav link → /admin dashboard (#254/#307) — entry point updated.

EOD batch (frontend mutation forms + task tracking):
- Security incident resolve form (#255/#309) — PATCH workflow для
  ФЗ-152 §17.1.
- PD request process form (#256/#310) — PATCH workflow для §15 SAR.
- KB user edit + deactivate form (#257/#311) — PATCH/DELETE workflow.
- Eval-runs trigger form (#258/#312) — POST с providers/test_set.
- /admin/maintenance — reindex + cache buttons (#259/#313).
- KB user create form (#260/#314) — POST closes user CRUD.
- Audit-log export form (#261/#315) — POST с reason для compliance.
- /admin/tasks/[id] (#262/#316) — task status detail, closes
  reindex/export/eval-runs task tracking loop.
- State-of-code EOD refresh (#317).
- Auto-polling /admin/tasks/[id] (#263/#318) — closes last self-serve
  CS.11 item.

ADR-0019 batch (Architect approved):
- ADR-0019 implementation (#264/#319) — system_config table + Settings
  merge layer + PATCH endpoint + PUT /admin/llm/active + X-MFA-Token
  honest stub. **OpenAPI 97/97 (100%) implemented.**
- LLM provider Switch UI (#265/#320) — PUT /admin/llm/active form per
  non-current provider.
- system-config edit form (#266/#321) — PATCH с diff-aware 5-keys form.
  Closes admin mutation surface (8th form today).

## CS.8. Webhook event taxonomy — completed

После landing'а PR #220-#225 — backend WebhookEvent enum полностью
покрывает OpenAPI §WebhookEvent перечисление **кроме**:
- `document.signed` — no trigger point (signing flow Stage 2 — нет
  signing UX; см. ADR-0023 Открытый вопрос §2).
- `service_order.{accepted, completed, failed}` — wiring backlog
  (требует partner-side endpoints для accept/complete/fail; cancel wired
  в #224).

`document.created` (#327, ADR-0023 B): emit site landit как
`documents.service.create_document(...)` orchestration helper. POST
/documents намеренно НЕ exposed на HTTP (Вариант B). Helper —
contracted entry point для будущих migration scripts / 1C / KYC
ingestion.

Все остальные **17 webhook events** имеют actual emit sites в backend:
- Articles: published, updated, archived.
- Documents: file upload audit (внутренний; не webhook).
- Chat: escalated, no_answer.
- Search: popular_query (daily aggregator worker).
- Premises: card.updated.
- Audit: security_event (target-bypass wiring; idempotency body mismatch — backlog).
- Collaborators: created, activated, suspended, archived, review.posted,
  portal_access.changed, onboarding.submitted.
- Service orders: created, cancelled.

Frontend `WEBHOOK_EVENTS` const tuple sync verified через
`test_events_frontend_sync` drift test.

## CS.9. Admin module (#227+) — 2026-05-23

Module `src/api/admin/` для `/api/v1/admin/*` endpoints. Landed в
22 endpoint'ах через 15 feature-PR'ов + alembic / docs / drift sync.

| Endpoint | PR | RBAC |
|---|---|---|
| GET /admin/stats | #227 | staff_admin |
| GET /admin/llm/providers | #228 | staff_admin |
| GET /admin/system-config | #229 | staff_admin |
| GET/POST /admin/users + GET/PATCH/DELETE /{id} | #230 | staff_admin |
| GET/PATCH /admin/security-incidents | #231 | staff_admin |
| GET/PATCH /admin/personal-data/requests | #232 | staff_admin |
| GET /admin/audit-log | #237 | staff_admin / staff_legal |
| DELETE /admin/cache | #238 | staff_admin (honest stub) |
| POST /admin/reindex | #240 | staff_admin (real for `articles` scope) |
| GET /admin/tasks/{id} | #238 | staff_admin |
| POST /admin/audit-log/export | #239 | staff_admin / staff_legal |
| POST/GET /admin/llm/eval-runs | #244 | staff_admin (mock+smoke MVP) |

`admin_tasks` table (#238) — universal async registry с lifecycle
PENDING → RUNNING → COMPLETED/FAILED/CANCELLED, используется reindex,
audit-log export и eval-runs.

**Remaining unimplemented OpenAPI admin endpoints** (2 — оба
design-needed, требуют writable runtime config storage):
- PATCH /admin/system-config (updateSystemConfig) — нужен ADR'а на
  system_config table + Settings merge layer + MFA-Token validation.
- PUT /admin/llm/active (setActiveLlmProvider) — coupled с
  system-config (одна из конкретных keys); same ADR покроет оба.

**Backlog (требует доработки имплементации):**
- ~~Real async worker для admin_tasks~~ ✅ DONE (#268, ADR-0020 B):
  `asyncio.create_task` spawn + `task_reaper` (15-min stale window).
  Phased migration к Dramatiq+Redis осталась backlog'ом при traffic
  ≥10 task/s или payloads ≥10MB.
- Real LLM providers в eval-runs (нужны env credentials).
- Cache layer (если landit — DELETE /admin/cache wires automatically).

## CS.10. ФЗ-152 module status (2026-05-22)

| Требование | Состояние | Реализация |
|---|---|---|
| ФЗ-152 §15 — субъектные запросы (SAR) | ✅ MVP (#232) | `/admin/personal-data/requests` registry + state machine (NEW→IN_PROGRESS→COMPLETED/REJECTED/OVERDUE) + 30-day SLA |
| ФЗ-152 §17.1 — security incidents | ✅ MVP (#231) | `/admin/security-incidents` registry + state machine + РКН notification fields (24h факт / 72h состав) |
| ФЗ-152 §19 — encryption в покое (HR ПДн) | ✅ MVP (#234, ADR-0018) | Fernet symmetric, env-managed key, MultiFernet rotation, 4 ПДн поля; ProductionReadinessGates: SOPS, runbook, физ.сейф (явно зафиксированы в ADR) |
| ФЗ-152 §22 — audit_log retention | ✅ MVP | 5-year retention default (через ADR-0009 backup tooling) |
| Маскировка ПДн в LLM context | ⏳ Stage 2 | RAG retrieval не подмешивает HR PII (физическая разделённость access_level); pre-processor masking — backlog |
| Уведомление РКН подано | ❌ Org task | Юр.процедура, не разработка |
| Назначение ответственного за ПДн | ❌ Org task | Приказ в ООО «РЕХОМ» |

ФЗ-152 compliance: ~70% технических мер реализовано или в process'е
review. Org-tasks (10-15%) — ответственность Архитектора.

## CS.11. Backlog приоритезация (2026-05-23 finale)

OpenAPI implementation coverage: **97/97 operations (100%)** после
landing'а 55 PR'ов. **All admin endpoints have both backend и frontend
UI implementations.**

Открытые задачи требующие design decision (architect input):
1. ~~PATCH /admin/system-config + PUT /admin/llm/active~~ ✅ DONE
   (#264 backend ADR-0019; #265 + #266 frontend forms).
2. **Vault Stage 2 emergency access** (2-of-2 escrow) — крипто-design
   (ADR-0021 Proposed, awaits architect approval).
3. **POST /documents create endpoint** — нужен в OpenAPI?
   (ADR-0023 Proposed, awaits architect approval).
4. **Real LLM credentials + golden dataset 200 pairs** — ops + content.
5. ~~Real async worker для admin_tasks~~ ✅ DONE (#268, ADR-0020 B):
   `asyncio.create_task` spawn + reaper для crash recovery. Phased
   migration к Dramatiq+Redis — backlog при ≥10 task/s.
6. **Keycloak step-up auth** для X-MFA-Token validation (#264 — пока
   honest stub; presence logged в audit но не verified).

Self-serve M-sized items без design дополнительного:
1. **Vault Stage 2 FIDO2** — WebAuthn integration (M, fresh). Нужен
   ADR для ceremony flow (ADR-0022 Proposed, awaits architect approval).
2. **Grafana dashboards** — JSON configs для существующих метрик
   (alert rules уже landit в #241/#293; dashboards — companion).
   Best built against running Grafana instance (PR #267 landed starter
   set, validation на running Grafana — backlog).
3. ~~Real `IndexerService.reindex_all_articles`~~ ✅ DONE (#240/#292).
4. ~~POST/GET /admin/llm/eval-runs~~ ✅ DONE MVP (#244/#297; mock+smoke).
5. ~~Frontend admin UI (read-only)~~ ✅ DONE (PRs #301-#307).
6. ~~LLMJudge MVP в eval-runs~~ ✅ DONE с MockJudge (#246/#299);
   faithfulness требует real LLMJudge — backlog (зависит от LLM creds).
7. ~~Admin mutation forms~~ ✅ DONE (#309-#315, #320, #321): incident
   resolve, PD request process, KB user create/edit/deactivate,
   eval-runs trigger, maintenance, audit-log export, LLM provider
   switch, system-config edit.
8. ~~Task tracking UI~~ ✅ DONE (#316).
9. ~~Auto-polling task status~~ ✅ DONE (#263/#318).

**Self-serve backlog exhausted.** Только items 1-2 остаются, оба нужны
preparation: ADR для FIDO2 ceremony / Grafana instance для testing.

Skipped explicitly (deferred):
- Legal contract rewrites (TD-004).
- Service payment sizing (TD-005).
- HR Stage 2 кэп-сертификаты / passport scans — отдельный flow через
  kb-files (ADR-0012 server-side encryption).

