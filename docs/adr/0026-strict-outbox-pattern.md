# ADR-0026: Strict outbox pattern — atomicity между business write, audit, webhook

## Статус

- [x] **Предложено** (awaiting Architect approval)
- [ ] Принято
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-25
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** **нет**, awaiting approval

## Контекст

Текущая architecture: при mutation endpoint (`POST /articles`,
`PATCH /articles/{slug}`, `DELETE /chat/sessions/{id}` и т.д.) handler
выполняет три отдельные операции:

1. **Business write** (article INSERT / UPDATE) — committed via
   `repo.create()` (commit ВНУТРИ repo).
2. **Audit log** (`audit_repo.record`) — отдельная транзакция.
3. **Webhook dispatch** (`webhook_dispatcher.dispatch`) — enqueue
   delivery rows, отдельная транзакция.

Известные race windows (markers в коде):

- `articles/router.py:464-466`: «audit log пишется в отдельную
  транзакцию ПОСЛЕ commit'а article'а ... Crash window между commit'ами
  ещё существует — strict outbox требует repo refactor (отдельный
  backlog).»
- `webhooks/dispatcher.py:10-15`: «trigger commit и delivery enqueue
  commit — две отдельные транзакции; small race window между ними
  (process crash → trigger зафиксирован, delivery нет). Принято: для
  MVP at-most-once acceptable; strict outbox — backlog.»
- `webhooks/dispatcher.py:70-73`: «Один сбой enqueue не должен ломать
  trigger или остальных subscriber'ов. Worker pick'нет недостающие на
  retry'ях отдельно — backlog.»

**Реальные failure modes:**

| Crash window | Effect |
|---|---|
| После article commit, до audit commit | Article exists, no audit row → compliance gap (ФЗ-152 §22 invariant нарушен). |
| После article commit, до webhook enqueue | Subscriber miss event («article.published» не доставлен). |
| Между webhook deliveries (один subscriber enqueued, второй не успел) | Partial fan-out, недетерминированно. |
| Webhook enqueue exception (DB hiccup) | Catch swallows — event silently dropped. |

Текущий compromise: «at-most-once acceptable для MVP» (`dispatcher.py:14`).
Это **нарушает** инвариант ФЗ-152 §22 (audit-trail completeness — все
write actions должны быть зафиксированы). Acceptable для greenfield
MVP без реальной нагрузки, но для production gating требуется fix.

## Решение

**Recommend Вариант C** (transactional outbox с background drainer).
Awaits Architect approval.

Высокоуровневая идея:
1. Single transaction commits triple: business write + audit_log row +
   `outbox` row (containing webhook event payload).
2. `OutboxDrainer` background worker (тот же pattern что
   `WebhookDeliveryWorker` / `PdOverdueWorker`) pick'ает unflushed
   outbox rows и delivers их в `webhook_deliveries` queue (или
   external sink на будущее).
3. Существующий `WebhookDeliveryWorker` дальше доставляет subscribers.

`outbox` table: `(id UUID PK, event_type TEXT, payload JSONB,
created_at TIMESTAMPTZ, flushed_at TIMESTAMPTZ NULL, retries INT
DEFAULT 0)`.

Workflow при `POST /articles`:
```
async with session.begin():  # single transaction
    article = await repo._insert_article(payload)  # NO inner commit
    await audit_repo.record(...)                    # same session
    await outbox_repo.enqueue(event_type, payload)  # same session
# Single commit at exit (success or rollback all)
```

Background `OutboxDrainer` (similar to `WebhookDeliveryWorker`):
```
while not shutdown:
    rows = await outbox_repo.fetch_unflushed(limit=100)
    for row in rows:
        try:
            await webhook_dispatcher.dispatch(row.event_type, row.payload)
            await outbox_repo.mark_flushed(row.id)
        except Exception:
            await outbox_repo.bump_retries(row.id)
```

## Альтернативы

### Вариант A — Skip (status quo, accept at-most-once)

Оставить current architecture. Document'ировать known compromise в
state-of-code, обновить ФЗ-152 §22 audit table статус с ✅ на 🟡.

**Pros:**
- Zero engineering work.

**Cons:**
- ФЗ-152 §22 audit-trail completeness compromise остаётся.
- Webhook miss'ы для compliance-critical events (article publish to
  external subscriber).
- Production gating заблокирован.

**Отклонено**: не решает compliance gap.

### Вариант B — Naive same-session writes (no outbox)

Refactor repos чтобы убрать inner `commit()` и принять external session
management. Handler делает single `async with session.begin():` обёртку
вокруг всех trio operations. Webhook dispatch остаётся как сейчас (best-
effort после commit).

**Pros:**
- No new table / migration.
- Audit + business write atomic — основной compliance gap закрыт.

**Cons:**
- Webhook dispatch всё ещё после commit'а → webhook miss window
  сохраняется (subscriber не получит published article).
- Требует repo refactor (remove inner commits) — широкий blast radius
  через ВСЕ repos. ~10+ repos затронуты.
- Не решает retries-on-enqueue-failure: если webhook enqueue падает —
  silent drop остаётся.

**Recommend if scope reduction нужен**, но Вариант C — более complete
solution.

### Вариант C — Transactional outbox + background drainer (recommended)

Описан выше.

**Pros:**
- Audit + business write + outbox enqueue — single transaction (ACID).
- Webhook dispatch eventually consistent через drainer (at-least-once
  гарантия — drainer retries on failure).
- ФЗ-152 §22 audit-trail completeness — fully closed.
- Outbox pattern широко используется (industry standard — see Microsoft
  Azure docs, Stripe, Shopify).
- Drainer ничего не блокирует — если падает, business write all равно
  consistent (outbox row sits и ждёт следующего drain pass'а).
- Pattern reuses singleton lifecycle infrastructure (#350) для
  drainer worker.

**Cons:**
- New `outbox` table + migration.
- Repo refactor scope: ~10 repos must remove inner commits + accept
  external session.
- Background worker overhead (~1 query per few seconds at drainer
  poll interval).
- Eventual consistency: subscriber может получить event с задержкой
  до next drainer poll (~1-5 sec). Acceptable для current SLA.
- New observability surface: drainer lag metric + outbox row count
  alert.

**Recommend.**

### Вариант D — Distributed transaction (XA / two-phase commit)

Полностью atomic commit business + webhook delivery row + external
notification. Требует XA-capable webhook subscribers — out of scope
(HTTP webhooks fundamentally не XA).

**Отклонено**: physically incompatible с HTTP webhook model.

## Последствия (если C принят)

### Положительные

- **ФЗ-152 §22 audit-trail completeness** — guaranteed by transaction.
- **Webhook at-least-once delivery** — guaranteed by drainer retries.
- Crash recovery: drainer's `flushed_at IS NULL` query на restart
  пик'ает orphaned outbox rows (same pattern as task_reaper).
- Compliance audit shows: «каждая business write имеет matching audit
  row» — provable invariant.
- Webhook dispatch decoupled от request hot path — handler latency
  снижается (no synchronous dispatcher round-trip).

### Отрицательные / компромиссы

- Eventual consistency (1-5 sec delay) для webhook delivery. Existing
  consumers (если есть) могут ожидать sub-second delivery.
- New monitoring surface: drainer worker uptime, outbox row count
  (если grows unbounded → drainer broken).
- Failure modes тестируемые но более complex (drainer crash mid-
  iteration, partial dispatch).
- Migration на existing data: ~0 outbox rows pre-migration (greenfield),
  но workers'ы стартуют с empty table.

### Технические следствия

**Migration:**
- `0030_outbox`: CREATE TABLE outbox (id, event_type, payload, created_at,
  flushed_at NULL, retries DEFAULT 0). Partial index `WHERE flushed_at
  IS NULL`. Retention 30 days (post-flushed cleanup).

**Backend:**
- `outbox/models.py`, `outbox/repository.py` — new module.
- `outbox/drainer.py` — new background worker (singleton via lifespan,
  per #350 pattern).
- `webhooks/dispatcher.py::dispatch` — refactor: вместо direct enqueue
  делегирует в outbox.enqueue (один insert вместо subscriber-loop
  enqueue), drainer fan-out'ит на multiple subscribers.
- `articles/repository.py`, `chat/repository.py`, etc. — remove inner
  `commit()`, accept external session (~10 repos).
- Handlers: wrap business write + audit + outbox.enqueue в
  `async with session.begin():`.

**Backend (incremental rollout — single repo PoC сначала):**
- Slice 1: outbox table + drainer + articles repo refactor (one repo).
- Slice 2: chat repo + collaborators repo.
- Slice 3: vault repo (security-sensitive — separate scrutiny).
- Slice 4: remove `webhook_dispatcher.dispatch` direct call, route
  everything через outbox.

**Tests:**
- Unit: outbox enqueue, drainer fetch + mark_flushed, retry on
  dispatch failure, crash recovery (orphaned rows pick up).
- Integration: full POST /articles → outbox row created → drainer
  flushes → webhook_deliveries enqueued → worker delivers.
- Crash simulation: inject exception между outbox enqueue commit и
  drainer pickup → restart → row should be picked up.

**Observability:**
- Prometheus: `outbox_pending_rows_total`, `outbox_drainer_iterations_total`,
  `outbox_drainer_lag_seconds`, `outbox_dispatch_failures_total`.
- Alert: drainer iterations не растут за 60 sec → worker stuck.

## Открытые вопросы для Архитектора

1. **Approve Вариант C** (transactional outbox) — рекомендуется?
2. **Slice rollout order**: articles first, потом chat / collaborators /
   vault? Или один большой PR?
3. **Drainer poll interval**: default 5 sec приемлемо? (Tradeoff:
   latency vs DB load.) Configurable через env.
4. **Outbox retention**: 30 days for flushed rows достаточно для
   forensic'а?
5. **`audit_repo.record` теперь должен принимать external session
   (без inner commit)** — refactor scope OK?
6. **Если drainer ОТКЛЮЧЁН** (env-gated like webhook worker) — что
   делать? Pile up outbox rows? Или fall back на direct dispatch
   (предположительно — да, env flag).
7. **Backward compat для existing webhooks code**: некоторые callers
   используют `webhook_dispatcher.dispatch` directly (см. chat
   /escalate, vault emergency unlock). Migration plan?

## Implementation gating

PR с реализацией создаётся ТОЛЬКО ПОСЛЕ ADR approve. Без approve'а
рассматривается как design-violation per CLAUDE.md §9.

Estimated scope (если B + C approved):
- Slice 1 (outbox foundation + articles): ~600 LOC backend + 200 tests.
- Slice 2-4: ~400 LOC each.
- Total: ~1800 LOC backend + ~600 LOC tests across 4 PRs.

## Ссылки

- ФЗ-152 §22 (audit-log retention + completeness).
- E5.2 #91 (existing webhook delivery worker — outbox для subscribers,
  same pattern reused for trigger fan-out).
- ADR-0020 §B (admin_tasks asyncio runner — singleton lifecycle precedent).
- Microsoft Azure Architecture Center: «Transactional Outbox pattern».
- Code markers: `backend/src/api/articles/router.py:464`,
  `backend/src/api/webhooks/dispatcher.py:10-15`.
