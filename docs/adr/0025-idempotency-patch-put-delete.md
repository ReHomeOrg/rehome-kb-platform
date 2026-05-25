# ADR-0025: Idempotency-Key extension на PATCH/PUT/DELETE — scope decision

## Статус

- [ ] Предложено
- [x] **Принято** (Вариант B) — 2026-05-25 Architect Evgeniy
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-25
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** **да**, 2026-05-25
- **Approve note:** Architect approved Вариант B (PATCH-only opt-in).
  Open-question resolutions:
  1. Вариант B confirmed.
  2. DELETE skip — natural 404 на retry достаточно (Stripe pattern).
  3. PUT skip — natural same-state idempotency.
  4. Single PR с 9 PATCH endpoints (manageable scope).
  5. Frontend opt-in — без mandatory header generation; existing
     callers work unchanged.

## Контекст

`Idempotency-Key` header support (E5.1 #44, ADR-implicit) сейчас
работает только для POST endpoints:
- POST /articles (#44)
- POST /admin/users (#230)
- POST /collaborators/{id}/service-orders (#226)
- POST /chat/sessions/{id}/escalate (#345, anon-aware variant)
- POST /collaborators/{id}/reviews (NO — не wired)
- ~20 других POST endpoints — НЕ wired (см. analysis ниже).

Backlog маркер в `idempotency/__init__.py:4`: «будущий расширение на
PATCH/PUT/DELETE использует те же helpers (E5.x backlog)».

**Реальная проблема:** retry на PATCH/PUT/DELETE сейчас вызывает:
- Duplicate audit_log rows (один на каждый retry).
- Duplicate webhook fires (subscribers получают N copies одного
  event'а).
- На PATCH с `if_match` (optimistic concurrency, ETag) — второй retry
  падает 412 потому что ETag сменился после первого UPDATE'а →
  client путается «применилось или нет?».

**Inventory (26 non-POST mutating endpoints в backend):**
- **9 PATCH**: admin/users, admin/security-incidents, admin/pd-requests,
  admin/system-config, premises, articles (PATCH partial), hr,
  collaborators, chat/feedback.
- **5 PUT**: articles full update, admin/llm/active, collaborators
  full update, vault unlock, vault group update.
- **12 DELETE**: articles, chat sessions, vault secrets/groups/shares,
  premises, hr, fido2, webhooks, collaborator junctions, admin/users
  (deactivate), admin/cache.

Не все равны:
- DELETE inherently idempotent at data level (second DELETE → 404).
- PUT inherently idempotent (same state).
- PATCH side effects (audit + webhook) проблематичны на retry.

## Решение

**Recommend Вариант B** (PATCH-only opt-in, PUT/DELETE skip). Awaits
Architect approval.

Применить `process_idempotency_key` к 9 PATCH endpoints где есть
non-trivial side effects (audit_log + webhook fire). PUT/DELETE — skip
(natural data-level idempotency достаточна).

Implementation: добавить `idempotency: IdempotencyResult = Depends(
process_idempotency_key)` в каждый PATCH endpoint, replay path в начале
handler, save на success.

Behaviour:
- `Idempotency-Key` header отсутствует → текущее поведение (no-op).
- Same key + same body → replay cached response (включая ETag).
  Audit / webhook НЕ fire'ятся повторно.
- Same key, different body → 409 (Stripe pattern).
- Invalid UUID → 422.

## Альтернативы

### Вариант A — Skip (statu quo)

Оставить idempotency только на POST. PATCH/PUT/DELETE callers полагаются
на natural data-level idempotency.

**Pros:**
- Zero code change.
- Меньше cache rows в `idempotency_keys` table.

**Cons:**
- Retry на PATCH → duplicate audit rows, duplicate webhooks. Это уже
  observed bug, не теоретический.
- ETag-mismatch ambiguity не разрешается (см. Контекст).
- Backlog маркер в idempotency/__init__.py остаётся.

**Отклонено**: не закрывает реальную observed проблему.

### Вариант B — PATCH-only (recommended)

Wire `process_idempotency_key` в 9 PATCH endpoints. PUT/DELETE skip.

**Pros:**
- Closes observed duplicate-audit / duplicate-webhook problem.
- Manageable scope: 9 endpoints + tests.
- Reuses existing `process_idempotency_key` infrastructure (no new
  table / migration / module).
- ETag flow клиенту чётче: retry с тем же body на PATCH с if_match —
  replay original 200 response с original ETag (no 412 confusion).
- Pattern: Stripe / GitHub также применяют idempotency только к
  endpoints с non-trivial side effects.

**Cons:**
- 9 endpoints × ~5 LOC на каждый wire = 45 LOC delta.
- 9 endpoints × ~4 unit tests на каждый = ~36 новых тестов.
- `idempotency_keys` table cache rows grow ~9× (still small — TTL 24h
  expiry уже implemented).
- Frontend must send Idempotency-Key UUID для retry-safety —
  documentation обновление.

**Recommend.**

### Вариант C — Universal (POST + PATCH + PUT + DELETE)

Wire idempotency в ВСЕ 26 mutating endpoints.

**Pros:**
- Consistent surface: any mutating endpoint accepts Idempotency-Key.
- Documentation simpler («all mutators support idempotency»).

**Cons:**
- DELETE: natural 404 на повторный delete — semantically OK. Replay
  возвращает успешный 204 — это инверсия (commit log говорит «delete
  succeeded» а данные уже не существовали при retry; client может
  попытаться restore). Stripe explicitly excludes DELETE.
- PUT: replay corner-case — если резерв был interim'но изменён между
  PUT и retry, replay вернёт original 200 но в БД — другое состояние.
  Misleading.
- 26 endpoints × overhead = ~3× больше scope vs B без proportional
  benefit.

**Отклонено**: PUT/DELETE add complexity без real bug fix.

### Вариант D — POST-only + auto-dedupe audit/webhook

Оставить idempotency только на POST. Решить duplicate side-effects через
deduplication на audit/webhook layer (e.g. `audit_log` table получает
unique constraint `(actor_sub, action, resource_id, created_at)`).

**Pros:**
- Idempotency surface не меняется.
- Defensive — даже non-idempotent retry не создаёт дубли.

**Cons:**
- audit_log spec не позволяет UQ на эту triple (multiple updates same
  field в один тимстамп legitimately possible).
- Webhook dedupe на subscriber-side — outside backend контроля.
- ETag-mismatch проблема не решается.

**Отклонено**: фундаментальное misalignment с audit/webhook semantics.

## Последствия (если B принят)

### Положительные

- Closes idempotency/__init__.py:4 backlog маркер.
- Removes observed duplicate-audit / duplicate-webhook на PATCH retry.
- ETag flow becomes retry-safe (cached response with original ETag).
- Pattern reusable for future endpoints (already established).

### Отрицательные / компромиссы

- Frontend / SDK clients нужно update: добавить `Idempotency-Key`
  header (UUID) на PATCH requests если они хотят retry-safety.
  Backwards-compatible default: без header — старое поведение.
- `idempotency_keys` table growth ~9× (TTL 24h всё ещё держит таблицу
  bounded; observed: low PATCH volume currently).

### Технические следствия

**Backend:**
- 9 PATCH endpoints получают `idempotency: IdempotencyResult = Depends(
  process_idempotency_key)`.
- В каждом — replay path в начале (4 LOC); save call после успешного
  flow (3 LOC).
- Existing `_process_for_actor` shared helper (#350) used as-is.

**Tests:**
- Per endpoint: no-key passes through (existing test); same-key +
  same-body replays; different-body → 409; invalid UUID → 422.

**OpenAPI:**
- Add `Idempotency-Key` header parameter ref в 9 operations.

**Frontend:**
- `lib/api/client.ts` — generate `Idempotency-Key` UUID per PATCH
  request (retry-loop wrapper). Backward-compat: existing direct calls
  без header работают идентично.

**Migration:** не требуется (`idempotency_keys` table уже unbounded на
`(key, request_path, actor_sub)` composite PK).

## Открытые вопросы для Архитектора

1. **Approve Вариант B** (PATCH-only) — рекомендуется?
2. **DELETE — точно skip?** Natural 404 на retry достаточно? Или
   хочется replay 204 для UX (no «duplicate request» error)?
3. **PUT — точно skip?** Natural same-state idempotency достаточно?
4. **Roll-out order:** один PR с 9 endpoints или 3 PR'а по domain
   (admin / articles / collaborators)?
5. **Frontend opt-in или mandatory?** Auto-generate Idempotency-Key
   header на каждый PATCH client-side?

## Implementation gating

PR с реализацией создаётся ТОЛЬКО ПОСЛЕ ADR approve. Без approve'а
рассматривается как design-violation per CLAUDE.md §9.

## Ссылки

- E5.1 #44 (foundation): POST idempotency-key
- #345: chat-specific anon idempotency variant
- #350: `process_for_actor` shared helper extraction
- Stripe Idempotency Keys docs (industry pattern reference): only POST
  by default, opt-in PATCH в их new API surface.
