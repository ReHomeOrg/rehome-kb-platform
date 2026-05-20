# ADR-0023: POST /documents create endpoint — scope decision

## Статус

- [ ] Предложено
- [x] **Принято** (Вариант B) — 2026-05-20 Architect Evgeniy
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-23 (предложено), 2026-05-20 (approved)
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Approve note:** Architect approved Вариант B — keep external-ingest
  only, wire `document.created` webhook via internal
  `DocumentRepository.create()` + `documents.service.create_document`.
  POST /api/v1/documents намеренно НЕ exposed на HTTP surface.
- **Follow-up decision 2026-05-20:** `title` (и `counterparty`) НЕ
  включаются в `document.created` webhook payload — machine-level only
  (document_id + category + status + confidentiality + created_at).
  Reason: external subscribers могут быть вне trust boundary
  (1C/CRM/partner integrations); document titles могут содержать имена
  контрагентов (ПДн). Subscriber retrieves full Document по
  `document_id` через GET /documents/{id} с собственным scope-фильтром.

## Контекст

OpenAPI 04 defines several `/documents` endpoints:
- `GET /api/v1/documents` (listDocuments) — ✅ implemented.
- `GET /api/v1/documents/{id}` (getDocument) — ✅ implemented.
- `POST /api/v1/documents/{id}/files` (uploadDocumentFile) — ✅
  implemented.
- `GET /api/v1/documents/{id}/files/{format}` (downloadDocumentFile) —
  ✅ implemented.

**Missing:** `POST /api/v1/documents` (create document metadata row).

Currently document rows ingested через:
- **External migration** — bulk import из legacy storage / 1C accounting
  при first deploy.
- **DocumentRepository.create()** — называется в backend tests + future
  internal workers, но не exposed на HTTP surface.

Two webhook events defined в `events.py` но не trigger'ятся (см. CS.8):
- `document.created` — no emit site (POST /documents absent).
- `document.signed` — no emit site (signing flow absent).

ТЗ §3 (PZ §6 «Хранилище юридических документов»):
- §6.1 — категоризация documents (типы A/B/C/D/E/F + lifecycle).
- §6.2 — метаданные (status: DRAFT / ACTIVE / EXPIRED / CANCELLED).
- §6.3 — версии + история changes (audit-log поверх migration).
- §6.4 — confidentiality tiers (PUBLIC / INTERNAL / RESTRICTED).

ТЗ НЕ упоминает explicitly «User создаёт document руками через API».
Документы изначально приходят из 1C (договоры аренды), legal team
(шаблоны), KYC providers (подписанные акты).

Архитектурные ограничения:
1. **POST /documents** означает HTTP surface для creating document
   metadata. Не для file upload — этот endpoint уже есть
   (POST /documents/{id}/files).
2. **ФЗ-152 implications**: document rows могут содержать subject_id,
   signed_by — ПДн. Поэтому RBAC должен enforce'ить scope.
3. **Audit invariant**: каждое creation audit'ится с actor_sub.

## Альтернативы

### Вариант A — POST /documents добавляется в OpenAPI + backend

**Endpoint:**
```
POST /api/v1/documents
{
  "category": "B",
  "subcategory": "rental_agreement",
  "title": "Договор аренды кв-001",
  "status": "DRAFT",
  "confidentiality": "INTERNAL",
  "subject_ids": ["uuid-tenant", "uuid-landlord"],
  "metadata": {"premises_id": "uuid-x"}
}
→ 201 {data: Document}
```

**Pros:**
- Closes OpenAPI semantic gap.
- `document.created` webhook event finally trigger'ится.
- Admin UI может позволить ручное создание (e.g. для drafts вне 1C).
- API consumers (Grafana automation? internal scripts?) могут create
  metadata rows.

**Cons:**
- **Duplicates business workflow**: legal docs создаются в 1C → migrate
  → этот POST по сути дублирует internal write path.
- **Security surface**: каждый endpoint = potential abuse vector
  (rate limit, validation, audit).
- **Schema bloat**: full Document shape валидно при create — много
  required fields, complex Pydantic.
- **Без consumer'а**: kто реально использовать будет? Admin UI MVP
  doesn't include create flow.

**RBAC:** `staff_legal` scope (юристы создают шаблоны) + `staff_admin`
для override scenarios.

### Вариант B — Keep external-ingest only (recommended)

**Не добавлять** POST /documents в OpenAPI / backend. Documents всегда
приходят через external migration / 1C / KYC integration.

**Webhook gap fix:**
- `document.created` event тригер'ить из internal `DocumentRepository.create()`
  (existing call в migration scripts) — событие emit'ит когда row insert
  происходит, независимо от HTTP path.
- `document.signed` — отдельный signal flow когда status переходит на
  ACTIVE с подписью (когда landит signing UX).

**Pros:**
- Keeps surface small (per ADR-0001 «не плодить endpoints»).
- Business workflow в 1C/legal остаётся authoritative.
- ФЗ-152: no extra HTTP path для ПДн ingest.
- Уже работает: list / get / upload / download достаточно для read-path
  ADR-0012 use cases.

**Cons:**
- OpenAPI имеет gap (документально). Frontend admin не может create
  draft без 1C round-trip.
- Webhook `document.created` всё ещё нужен trigger — но из internal
  path, не HTTP.

### Вариант C — Hybrid: POST /documents через service endpoint (internal-only)

POST endpoint существует но не exposed внешнему миру:
- `POST /api/v1/admin/documents` (NOT `/api/v1/documents`) — staff_admin
  scope only.
- Используется admin UI / migration scripts / internal automation.
- External integrations (1C / KYC) продолжают использовать direct DB
  inserts через migration script.

**Pros:**
- Closes OpenAPI gap for internal use cases.
- Не exposes на public surface (rate limit risk).
- Migration scripts всё ещё работают (bulk DB insert > endpoint loop).

**Cons:**
- Hybrid path — два code-path для creation.
- Internal automation мог бы напрямую через DocumentRepository (без
  endpoint).

## Рекомендация

**Вариант B (keep external-ingest only)** — c небольшим follow-up:
- Add `document.created` webhook trigger в `DocumentRepository.create()`
  для closing CS.8 gap.
- Remove `POST /api/v1/documents` упоминания из OpenAPI (если есть
  draft mention) или mark explicitly как «out-of-scope: ingest через
  migration».

Аргументация:
- Нет clear consumer для POST endpoint в ТЗ.
- Business реальность: documents authoritative в 1C; reHome — read-only
  consumer для compliance review.
- Минимальный security surface preferable.
- Если consumer появится позже — Вариант C (admin-scoped) можно
  добавить как escape hatch без public exposure.

## Implementation scope (если B approved)

**Backend:**
1. `DocumentRepository.create()` — pure-storage INSERT с enum-валидацией
   (raises ValueError до flush).
2. `documents.service.create_document(repo, audit_repo, dispatcher, ...)` —
   orchestration helper: create + audit + webhook. Single internal
   entry point — future migration scripts / 1C / KYC ingestion calls
   через этот helper чтобы webhook emission гарантировался.
3. OpenAPI: POST /api/v1/documents намеренно отсутствует. ADR
   ссылается на это как explicit out-of-scope.

**Frontend:**
- No new admin UI surface для create (Вариант B-decision).

**Tests:**
- Unit `tests/unit/documents/test_create_service.py`:
  - DocumentRepository.create() — validation rejects bad enum / malformed
    related_entity, flush + refresh on success.
  - create_document() — audit row + webhook dispatch с правильным
    payload; metadata machine-level (без PII в audit JSONB);
    validation error при repo.create propagates без side effects.
- Drift sync: WebhookEvent enum включает `document.created` (уже есть).

## Открытые вопросы для Архитектора

1. **Approve Вариант B** (external-ingest, recommended) или A
   (POST endpoint full) / C (internal admin endpoint)?
2. **`document.signed` webhook**: когда landит signing flow? Stage 2?
   (Сейчас status='ACTIVE' set через migration, нет signing UX.)
3. **Если B + future Вариант C**: какой timeline для admin endpoint
   needed? (Зависит от admin UI roadmap.)
4. **OpenAPI cleanup**: explicitly remove POST /documents reference
   from spec, or add `x-implementation-status: out_of_scope` per
   Вариант B?

## Implementation gating

PR с реализацией создаётся ТОЛЬКО ПОСЛЕ ADR approve. Без approve'а
рассматривается как design-violation per CLAUDE.md §9.
