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

