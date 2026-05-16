# ADR-0014: Collaborators foundation — модель + CRUD MVP slice

## Статус

[ ] Предложено
[x] Принято
[ ] Заменено ADR-MMMM
[ ] Отклонено

- **Дата:** 2026-05-16
- **Автор:** Агент-Разработчик
- **Согласовано Архитектором:** да, 2026-05-16 (чат-сессия, scope approved)

## Контекст

ТЗ §10 «Коллаборанты и внешние контрагенты» (ПЗ «База знаний v1.4»)
определяет единую сущность `Collaborator` с 14 типами (`management_company`,
`emergency_service`, `repair_handyman`, `cleaning`, `moving`, `key_delivery`,
`insurance`, `payment_partner`, `kyc_provider`, `edo_provider`, `sms_voice`,
`it_infrastructure`, `legal_consultant`, `other`) и 4 финансовыми группами
(A/B/C/D). API §3.10 описывает 6 подразделов с ~16 endpoint'ами, плюс
2 спец-эндпойнта v1.0 (`/onboarding`, `/portal-access`).

Текущий код (main, 2026-05-16):
- Нет `collaborators` table, нет миграции.
- Нет `src/api/collaborators/` module.
- API §3.10 endpoints отсутствуют.
- Только упоминание в ТЗ + текстовая ссылка в OpenAPI.

Полная реализация эпика — большая (~6 PR slices). Этот ADR фиксирует
**Slice 1: Foundation + CRUD** (~5 endpoints), оставляя остальное
(`lifecycle`, `onboarding`, `portal-access`, `metrics`, `PremisesCollaborator`,
`reviews`, `service_orders`) на отдельные slices.

Открытые вопросы перед стартом:

- Как `financial_group` связана с `type` — derived или explicit invariant?
- Как `access_level` вычисляется per collaborator (D-группа = public контакт,
  A/B/C = internal данные)?
- 404 mask на out-of-scope — тот же ADR-0003 pattern, что в documents?
- `contacts` JSONB shape — Pydantic-only или DB CHECK?

## Решение

### 1. Scope Slice 1 — 5 CRUD endpoints + foundation

In scope:
- Migration `0018_collaborators_foundation.py` со всеми полями ТЗ §10.5
  (без `metrics` aggregate — это compute-on-read, не storage).
- `src/api/collaborators/` module: models, schemas, repository, router,
  access mapping.
- 5 endpoints: list (с фильтрами), get, post (DRAFT default, D auto-ACTIVE),
  patch, delete (archive).
- Audit constants: `RESOURCE_COLLABORATOR`, `ACTION_COLLABORATOR_CREATED`,
  `ACTION_COLLABORATOR_UPDATED`, `ACTION_COLLABORATOR_ARCHIVED`.
- ADR-0003 enforcement на storage level (SQL WHERE).
- Unit tests + integration test stub.
- OpenAPI sync для 5 endpoints.

Out of scope (явный backlog):
- `POST /api/v1/collaborators/{id}/activate` + `/suspend` — Slice 2.
- `POST /api/v1/collaborators/onboarding` (public form, no auth) — Slice 3.
- `PUT /api/v1/collaborators/{id}/portal-access` — Slice 3.
- `GET /api/v1/collaborators/{id}/metrics` — Slice 4 (требует aggregation
  queries over service_orders / reviews).
- `PremisesCollaborator` junction + endpoints — Slice 5.
- `Reviews` endpoints — Slice 6.
- `Service Orders` (escrow) — отдельный эпик (требует payment partner).
- Dadata/Контур.Фокус integration для `counterparty_check` — backlog
  (Phase 1, partner integration).
- Frontend admin pages — отдельный PR после backend.

### 2. `type` ↔ `financial_group` — explicit column с CHECK constraint

ТЗ §10.3 даёт **закреплённую** mapping таблицу (architect-approved):

| type | financial_group |
|------|-----------------|
| payment_partner, kyc_provider, sms_voice, it_infrastructure, edo_provider, legal_consultant | A |
| cleaning, moving, key_delivery, repair_handyman | B |
| insurance | C |
| management_company, emergency_service | D |
| other | (любая — manual choice) |

**Решение**: `financial_group` — explicit column в таблице (не derived).
Mapping enforced через **CHECK constraint** в миграции:

```sql
CHECK (
  (type = 'payment_partner' AND financial_group = 'A')
  OR (type = 'kyc_provider' AND financial_group = 'A')
  -- ... все 13 invariant pairs ...
  OR (type = 'other')  -- 'other' — any group
)
```

Почему explicit + CHECK, не derived:
- DRY это appealing, но `other` тип ломает invariant (любая группа).
- CHECK constraint — single source of truth в БД, защищён от прямого
  SQL UPDATE без application validation.
- Application слой (Pydantic + model) добавляет дополнительную проверку,
  но БД — последняя линия защиты.

Альтернатива: одна колонка `type`, financial_group вычисляется в repository.
Отвергнута: при manual SQL operations / dashboards отсутствие explicit
group делает analytics queries painful.

### 3. `access_level` — derived из `financial_group`, фильтр на SQL уровне

ТЗ §10.7 говорит "контакты УК/ТСЖ" видит жилец → group D — публичный.
Остальные группы (A/B/C) — internal данные (юр.реквизиты, финансовые условия,
API ключи), staff-only.

**Решение**: не вводим отдельную колонку `access_level`. Вместо неё —
SQL фильтр через `financial_group`:

```python
# В repository:
allowed_groups: set[str] = compute_visible_groups(access_levels)
# guest / PUBLIC scope → {'D'}
# tenant / LOGGED → {'D'}  (LOGGED не дополняет collaborators visibility)
# staff_support / STAFF → {'A', 'B', 'C', 'D'}
# staff_admin → {'A', 'B', 'C', 'D'} + полный аудит-лог
stmt = select(Collaborator).where(Collaborator.financial_group.in_(allowed_groups))
```

Поэлементное маскирование полей detail-view'а (юр.реквизиты, financial_terms,
api_integration) — внутри router'а через Pydantic schema branching
(PublicCollaboratorMeta vs StaffCollaboratorView). Pattern из documents
(detail с signed_by + audit_log).

**404 mask**: запрос guest'а на A/B/C коллаборанта → 404 (anti-enumeration,
тот же pattern что в documents/articles).

### 4. `contacts` — JSONB с Pydantic schema, без DB CHECK

`contacts` — массив объектов:
```python
class ContactEntry(BaseModel):
    phone: str | None
    email: str | None
    messenger: str | None       # "telegram://..." или "whatsapp://..."
    emergency_channel: bool
    person_name: str | None     # ФИО
    person_role: str | None     # должность

# В model:
contacts: Mapped[list[dict]] = mapped_column(JSONB, default=list)
```

Pydantic валидирует структуру на API boundary. DB CHECK на JSONB
содержимое — overengineering для MVP (нет direct SQL inserts без
application).

`person_name` — это ПДн → ФЗ-152: видна только тем scope'ам, что видят
ту же financial_group. Pydantic schema разделение
(`CollaboratorPublic` без person_name vs `CollaboratorInternal` с ним).

### 5. Status lifecycle — enum, без транзишн-machine в Slice 1

ТЗ §10.5 даёт 5 статусов: `DRAFT | PENDING_REVIEW | ACTIVE | SUSPENDED | ARCHIVED`.

В Slice 1:
- POST: status=DRAFT (default), кроме D-группы → status=ACTIVE автоматически
  (ТЗ §3.10.1).
- PATCH: status field обновляется напрямую, но **переходы не валидируются**
  (любой → любой). Это намеренная неполнота — full transition validation
  с invariant'ами (`ACTIVE only if counterparty_check=CLEAN`) — Slice 2
  (`/activate` endpoint).
- DELETE: status → ARCHIVED.

CHECK constraint на enum — обязательный.

### 6. `audit_log` — массив JSONB в той же таблице (pattern из documents)

```python
audit_log: Mapped[list[dict]] = mapped_column(JSONB, default=list)
# entries: {actor: sub, action: 'updated', ts: ISO8601, changes: {...}}
```

Дублирует общий `audit_log` table — намеренно, потому что:
- Quick `GET /collaborators/{id}` показывает history без JOIN.
- Общий audit_log table — для centralized search; per-resource log —
  для быстрого detail view.

Pattern из documents (`documents.audit_log` JSONB column + RESOURCE_DOCUMENT
entries в audit_log table).

### 7. Field visibility per scope (table)

| Поле | guest/PUBLIC | tenant/LOGGED | staff_support/STAFF | staff_admin |
|------|--------------|---------------|---------------------|-------------|
| id, type, brand_name, service_area, working_hours, website | ✓ (только D) | ✓ (только D) | ✓ | ✓ |
| name (юр. название) | ✗ | ✗ | ✓ | ✓ |
| inn, ogrn, kpp | ✗ | ✗ | ✓ | ✓ |
| contacts (phone, email, emergency_channel) | ✓ (только D) | ✓ (только D) | ✓ | ✓ |
| contacts.person_name, person_role | ✗ | ✗ | ✓ | ✓ |
| financial_terms, sla, api_integration | ✗ | ✗ | ✓ | ✓ |
| responsible_internal | ✗ | ✗ | ✓ | ✓ |
| counterparty_check | ✗ | ✗ | ✓ | ✓ |
| audit_log | ✗ | ✗ | ✗ | ✓ |
| rating | ✓ | ✓ | ✓ | ✓ |

Реализация: 2 Pydantic response schemas:
- `CollaboratorPublic` (для D-группы guest/LOGGED view)
- `CollaboratorInternal` (extends public, для STAFF+)
- `CollaboratorAdmin` (extends internal, для staff_admin — добавляет audit_log)

Router branch'ит response_model по effective scope.

### 8. Test strategy

- Unit tests на access mapping (`compute_visible_groups`), Pydantic schema
  validation, repository SQL stmt compilation (без БД).
- Integration test stub (skipped до Slice 2 lifecycle): seed D + A collaborator
  → guest sees only D, staff sees both.
- Drift sync test: backend Literal `CollaboratorType` ↔ migration CHECK
  constraint enum (pattern из articles).

## Альтернативы

### A. Микросервис `kb-collaborators`

Pro: clean boundary, independent deploy.
Con: 14 типов имеют пересечение с documents (contract_document_id),
audit, premises (PremisesCollaborator junction). Дополнительный сервис
→ JOIN через RPC → латентность + complexity без явной пользы.
Отвергнуто.

### B. `financial_group` derived в repository, без БД колонки

Pro: DRY, нет risk drift между БД и code.
Con: `other` тип ломает 1:1 mapping (любая группа), плюс analytics
queries без explicit column сложнее.
Отвергнуто — explicit column + CHECK.

### C. Отдельная колонка `access_level` (как в articles)

Pro: единый pattern с articles.
Con: дублирует `financial_group` (D ↔ PUBLIC), создаёт risk inconsistency.
Отвергнуто — derive из `financial_group`.

### D. Per-field masking через row-level security (RLS) Postgres

Pro: enforcement на самом низком уровне, защита от прямых SQL.
Con: усложняет migrations, debugging, integration tests; pgvector/pgbouncer
compat. Не используется в проекте сейчас (articles, documents).
Отвергнуто — application-level enforcement consistent с rest of code.

## Последствия

### Позитивные

- Foundation готова для всех остальных slice'ов (lifecycle, onboarding,
  metrics, junction).
- CHECK constraint защищает от accidentally-malformed inserts.
- ADR-0003 pattern (storage-level WHERE filter + 404 mask) проверен — еще
  одна enforcement-точка.
- 5 endpoints достаточно для contract testing partner'ами (clients
  начинают строить интеграцию до landing'а остальных endpoints).

### Негативные / риски

- Slice 1 не возвращает реалистичный полный flow — admin может создать
  ACTIVE collaborator без активации через `/activate`. До Slice 2
  это temporal incoherence (документация говорит: "use POST → DRAFT
  → manually PATCH status=ACTIVE" — workaround).
- `counterparty_check` JSONB не валидирован против external service —
  пока store как-есть. Slice 4+ добавит Dadata integration.
- Field masking через 3 Pydantic schemas — boilerplate. Если scope-set
  расширится (новые типы scope) — потребуется добавлять schemas.
  Acceptable trade-off для MVP.

## Backlog (явно отложено)

1. **Slice 2** (`/activate` + `/suspend`): transition validation,
   invariant'ы (counterparty_check=CLEAN для activate group A/B/C),
   contract_document_id required.
2. **Slice 3** (`/onboarding` + `/portal-access`): public form без auth
   (rate-limit + captcha), portal tier change с history.
3. **Slice 4** (`/metrics`): aggregation queries по service_orders /
   reviews, кэширование.
4. **Slice 5** (`PremisesCollaborator` junction): + endpoints
   `GET/POST/DELETE /api/v1/premises/{id}/collaborators`.
5. **Slice 6** (`reviews`): + rating recompute trigger.
6. **Service Orders** (escrow) — отдельный эпик, требует payment partner.
7. **Dadata integration** для `counterparty_check`.
8. **Frontend admin pages** (`/admin/collaborators`).

## Ссылки

- ТЗ §10 «Коллаборанты» — `docs/handoff/01_postanovka/01_База_знаний_структура.md`
- API §3.10 — `docs/handoff/01_postanovka/03_API_базы_знаний.md`
- ADR-0003 — Storage-level access enforcement (фильтр на SQL)
- ADR-0012 — Documents (pattern для JSONB audit_log + scope-aware schemas)
