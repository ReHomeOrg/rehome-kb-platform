# ADR-0015: Collaborators Slice 3 — onboarding (public) + portal_access tier

## Статус

[ ] Предложено
[x] Принято
[ ] Заменено ADR-MMMM
[ ] Отклонено

- **Дата:** 2026-05-17
- **Автор:** Агент-Разработчик
- **Согласовано Архитектором:** да, 2026-05-17 (чат-сессия, scope approved)

## Контекст

ТЗ §10.8 «UI и личный кабинет коллаборанта» (ПЗ «База знаний v1.4»)
утвердил гибридную модель: коллаборант **сам выбирает** уровень
кабинета при онбординге — NONE / LIGHT / FULL. УК/ТСЖ и аварийные
службы — auto-NONE.

API §3.10 (v1.0 expansion) добавил 2 endpoint'а:
- `POST /api/v1/collaborators/onboarding` — публичная форма
  самостоятельной заявки. **Без авторизации** (rehome.one/partners
  — лендинг).
- `PUT /api/v1/collaborators/{id}/portal-access` — смена уровня
  кабинета. Понижение в любой момент; повышение — после первой
  успешной операции или одобрения оператором.

Slice 1-2 collaborators (ADR-0014) реализовал CRUD + lifecycle, но
без portal_access поля и без public-form endpoint'а. ADR-0015
закрывает Slice 3.

Открытые вопросы:

- **Public endpoint без auth** — как защититься от спама/abuse?
- **portal_access_level** — отдельная колонка или JSONB?
- **portal_access_history** — формат audit trail смен tier'а?
- **onboarding_source** — какие значения отслеживать (форма / приглашение / API / manual)?
- **Promotion rule** — кто решает что "первая успешная операция"
  состоялась? Кто approve'ит manual promotion?

## Решение

### 1. Scope Slice 3 — 2 endpoints + migration

In scope:
- Migration `0020_collaborators_portal_access.py`:
  - `portal_access_level` колонка (NONE/LIGHT/FULL, default NONE)
  - `portal_access_history` JSONB array (хранит смены: from/to/by/ts/reason)
  - `onboarding_source` enum колонка (form/staff_invite/api/migration)
- `POST /api/v1/collaborators/onboarding` — public endpoint без auth
- `PUT /api/v1/collaborators/{id}/portal-access` — STAFF+ для повышения,
  любой owner для понижения (Slice 3 — пока STAFF-only, owner-flow
  Slice 4 когда добавится Collaborator user account)
- Pydantic schemas + Literal sync test
- 2 audit actions: `ACTION_COLLABORATOR_ONBOARDED`,
  `ACTION_COLLABORATOR_PORTAL_ACCESS_CHANGED`
- Unit tests

Out of scope (явный backlog):
- **Captcha** — Slice 3.5 когда подключится hCaptcha/Cloudflare Turnstile
  provider. В MVP — только rate-limit + soft validation.
- **Email verification** — отдельный flow подтверждения адреса
  коллаборанта. Backlog (требует SMTP integration).
- **Auto-promotion после первой успешной операции** — требует
  service_orders epic (B-группа escrow). Backlog Slice 5.
- **Collaborator user account** — отдельная сущность для логина в
  личный кабинет. Slice 4 (требует Keycloak realm extension).
- **Webhook на onboarding event** — `collaborator.onboarding.submitted`
  + `collaborator.portal_access.changed` уже в webhooks/events.py
  enum, но fire'ить из router'а в Slice 3 — backlog (требует
  refactor webhook dispatcher для in-process trigger).

### 2. Public endpoint защита — rate-limit без captcha в MVP

`POST /collaborators/onboarding` — единственный no-auth write endpoint
в kb-api. Без захищы — open spam vector.

**Решение MVP:**

- **Rate-limit by IP**: max 5 заявок / IP / час (in-memory bucket,
  reset при restart'е). Превышение → 429 Too Many Requests.
- **Validation soft**: required fields (name, type, contact email/phone,
  service_area). Поле `type` ∈ Literal — Pydantic 422 на bogus values.
- **counterparty_check.result** не trust'им из payload'а — staff'у
  всё равно надо проверять Dadata-ом перед activation.
- **No captcha в MVP** — captcha добавит external dependency
  (hCaptcha/Turnstile), их интеграция — Slice 3.5. Rate-limit достаточно
  до landing'а первого реального трафика; metrics покажут нужно ли.

Status онбординг'нутого коллаборанта = **PENDING_REVIEW** (ТЗ §3.10:
"оператор рассматривает"). Activation через `/activate` endpoint
(Slice 2) — staff manually triggers после Dadata check.

Anti-leakage: response не возвращает inn/ogrn/contacts из payload'а —
только `{id, status: "PENDING_REVIEW", message}`. Защита от enumeration
типа "проверь, существует ли уже такой ИНН в системе".

### 3. `portal_access_level` — отдельная колонка с CHECK enum

```sql
ALTER TABLE collaborators
  ADD COLUMN portal_access_level VARCHAR(10) NOT NULL DEFAULT 'NONE'
  CHECK (portal_access_level IN ('NONE', 'LIGHT', 'FULL'));
```

Не derive из financial_group: ТЗ §10.8 явно говорит "выбор самого
коллаборанта", D-группа auto-NONE — только default, не invariant
(хотя в практике D-группа всегда NONE).

`portal_access_history`:
```sql
ADD COLUMN portal_access_history JSONB NOT NULL DEFAULT '[]'::jsonb;
```

Структура entry:
```json
{
  "from": "LIGHT",       // null для initial set
  "to": "FULL",
  "by": "<actor_sub>",
  "ts": "2026-05-17T...",
  "reason": "approved promotion"
}
```

Single JSONB column (не отдельная таблица) — pattern из documents.audit_log:
- Quick read с detail
- Не делаем JOIN на каждый detail-view
- Для bulk search в БД (compliance) — отдельный audit_log table уже есть

### 4. `onboarding_source` enum

```python
OnboardingSource = Literal[
    "form",          # самозаявка через /onboarding
    "staff_invite",  # staff создал через POST /collaborators
    "api",           # automated bulk import (Slice future)
    "migration",     # backfilled from legacy system
]
```

Default для existing rows (Slice 1+2 create) — `staff_invite` (через
migration default). Для `/onboarding` — `form`. `api`/`migration` —
зарезервировано для Slice 4+ flows.

CHECK constraint на enum + Literal sync test (тот же pattern, что и
type/financial_group/status в migration 0019).

### 5. Portal access transitions — три типа

ТЗ §10.8.1:
- **Понижение** (FULL→LIGHT, LIGHT→NONE, FULL→NONE) — в любой момент,
  любым actor'ом (owner или staff). В Slice 3 — STAFF-only потому что
  ещё нет collaborator user account.
- **Повышение** (NONE→LIGHT, LIGHT→FULL, NONE→FULL) — после первой
  успешной операции **или** одобрения оператором.
- **`from FULL to NONE`** — soft delete: 90 дней → ARCHIVED
  (background job, Slice 5).

В Slice 3 endpoint `/portal-access` validates только enum value;
"first successful operation" detection — backlog (требует service_orders).

`portal_access_history.reason` поле — required для повышения, optional
для понижения (audit trail).

### 6. Onboarding payload shape

```python
class OnboardingRequest(BaseModel):
    name: str = Field(min_length=2, max_length=500)
    brand_name: str | None = Field(default=None, max_length=200)
    type: CollaboratorType  # Literal — 14 типов
    legal_entity_type: LegalEntityType | None = None
    inn: str | None = Field(default=None, pattern=r"^\d{10}$|^\d{12}$")
    service_area: str = Field(min_length=3, max_length=500)
    contact: ContactEntry  # ровно один контакт обязателен (телефон ИЛИ email)
    portal_access_level_requested: Literal["NONE", "LIGHT", "FULL"] = "LIGHT"
    message: str | None = Field(default=None, max_length=2000)
```

Pydantic validation:
- `inn` — regex 10 или 12 digits (Pydantic level).
- `contact` — at least one of phone/email (model_validator).
- `portal_access_level_requested` — caller-stated preference; staff может override при activation.

Response:
```python
class OnboardingResponse(BaseModel):
    id: UUID
    status: Literal["PENDING_REVIEW"]
    message: str  # "Заявка получена, оператор свяжется с вами"
```

`financial_group` auto-derive из type (для всех кроме `other` — там
default A до review). `other` коллаборант через self-form запрещён —
422 с reason "type=other требует staff_invite".

### 7. Rate-limit implementation — in-memory bucket (без Redis)

```python
class IPRateLimiter:
    """Token bucket per IP. In-memory, per-process. MVP scale."""
    _windows: dict[str, list[float]] = {}  # ip → [timestamps]
    MAX_REQUESTS = 5
    WINDOW_SECONDS = 3600

    def check(self, ip: str) -> bool:
        now = time.time()
        bucket = self._windows.setdefault(ip, [])
        bucket[:] = [t for t in bucket if now - t < self.WINDOW_SECONDS]
        if len(bucket) >= self.MAX_REQUESTS:
            return False
        bucket.append(now)
        return True
```

Backlog: distributed rate-limit через Redis (Slice 5+), nginx-level
limit (production deploy), captcha (Slice 3.5).

In-memory rate-limit сбрасывается при rolling deploy / pod restart —
acceptable для MVP. Spam attacker может попробовать timing — но 5/hour
IP — это >100 manual попыток в день, всё равно triage'ить staff'ом.

`X-Forwarded-For` header trust только если есть `TRUSTED_PROXIES`
env config (anti-spoof). Default: использовать `request.client.host`.

### 8. Audit invariants

- Каждый onboarding пишет `ACTION_COLLABORATOR_ONBOARDED` с
  `metadata={type, source: 'form', ip_hash: sha256(ip)[:16]}`.
- Каждый portal-access change пишет
  `ACTION_COLLABORATOR_PORTAL_ACCESS_CHANGED` с
  `metadata={from, to, reason}`.

IP hashed (не в plain) для ФЗ-152 + 5y retention — IP это persistent
identifier, требует обоснования хранения.

## Альтернативы

### A. Captcha required с первого дня

Pro: серьёзный спам-щит.
Con: external dependency, integration overhead, UX friction. Прод-метрики
покажут реальный объём abuse прежде чем тратить cycle.
Отвергнуто — defer до Slice 3.5.

### B. Email verification first (magic link)

Pro: гарантирует что email рабочий, soft anti-spam.
Con: требует SMTP integration (sms_voice provider — A-группа коллаборант,
chicken-and-egg). Backlog.
Отвергнуто для MVP.

### C. `portal_access_level` в `financial_terms` JSONB

Pro: меньше колонок.
Con: нет CHECK на enum value, нет SQL фильтрации по уровню для analytics.
Отвергнуто — explicit column.

### D. Отдельная таблица `portal_access_history`

Pro: pure SQL queries для history search.
Con: JOIN на каждый detail-view; общий audit_log table уже есть для bulk
search.
Отвергнуто — JSONB column consistent с documents pattern.

## Последствия

### Позитивные

- Закрывается ТЗ §10.8 и API §3.10 (onboarding + portal-access).
- Public-form endpoint без regression в auth flow для всех остальных
  endpoints.
- portal_access_history даёт compliance trail для аудита.

### Негативные / риски

- In-memory rate-limit не работает между pods/instances. Acceptable
  для current single-pod local dev; production deploy потребует Redis-
  based rate-limit (вынести в middleware).
- Без captcha attacker может перебрать 5/hour × IP-rotation. Realistic
  threat — solicited spam from competitor; mitigation: staff triages
  PENDING_REVIEW каждый день.
- `portal_access_level_requested` — caller-controlled, staff override
  при review. Если staff не review'ит — collaborator остаётся PENDING
  с пользователь-указанным level. UX risk: коллаборант ждёт. Mitigation:
  Slice 4 webhook на staff support о новой заявке.

## Backlog (явно отложено)

1. **Slice 3.5 captcha** — hCaptcha/Cloudflare Turnstile integration.
2. **Email verification** — SMTP partner integration + magic link.
3. **Distributed rate-limit** — Redis-based, Slice 5+.
4. **Auto-promotion после первой successful operation** — Slice 5
   (требует service_orders).
5. **Collaborator user account + login** — Slice 4 (Keycloak realm
   extension).
6. **Webhook fire** на `collaborator.onboarding.submitted` +
   `collaborator.portal_access.changed` — refactor dispatcher для
   in-process triggers.
7. **`from FULL to NONE` 90-day archive cron** — Slice 5.
8. **Frontend `/admin/collaborators/onboarding-queue`** — UI для staff
   просмотра PENDING_REVIEW.

## Ссылки

- ТЗ §10.8 — `docs/handoff/01_postanovka/01_База_знаний_структура.md`
- API §3.10 — `docs/handoff/01_postanovka/03_API_базы_знаний.md`
- ADR-0014 — Collaborators foundation (предшественник)
- ADR-0003 — Storage-level access enforcement
