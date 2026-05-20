# ADR-0020: Async worker для admin_tasks (Redis+Dramatiq vs asyncio runner)

## Статус

- [ ] Предложено
- [x] **Принято**
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-23
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** да, 2026-05-23 (Вариант B — asyncio.create_task
  pattern на MVP scale, переход на A когда production volumes требуют).

## Контекст

Три admin endpoints создают `admin_tasks` rows и выполняют work
синхронно в request handler'е (CLAUDE.md «honest stub», см. CS.9):

| Endpoint | PR | Sync issue |
|---|---|---|
| POST /admin/reindex | #240 | N×embed_latency (~50s на 1000 articles) |
| POST /admin/audit-log/export | #239 | CSV generation для 10k rows (~5s) |
| POST /admin/llm/eval-runs | #244 | per-pair LLM calls (~minutes для real LLM) |

Current behavior:
- Caller блокируется на request duration.
- Worker process crash mid-request → task застрянет в `RUNNING` без
  reaper. (UI auto-polling показывает старый status вечно.)
- Production volumes (1000+ articles, 200-pair golden dataset с real
  LLM) — превышает разумный HTTP timeout.

Архитектурные ограничения:
1. **ФЗ-152** — все workers и queues в РФ. Внешние SaaS queue
   (SQS, Cloud Tasks) исключены.
2. **CLAUDE.md §6** — не подключать новые external services без ADR
   и approve. Redis = new service → требует этого ADR.
3. **Self-hosted bias** — open-source предпочтительнее managed.
4. **ADR-0010** webhook worker уже использует asyncio.create_task
   pattern (без Redis); reference implementation существует.

## Альтернативы

### Вариант A — Dramatiq + Redis (production-scale)

**Stack:** [Dramatiq](https://dramatiq.io/) — Python distributed task
queue с pluggable broker. Redis broker — стандартный (RAM-based, low
latency, RESP protocol). Self-hosted Redis в РФ — OK по ФЗ-152.

**Pipeline:**
```
POST /admin/reindex
  → repo.create(type='reindex', status='PENDING')
  → dramatiq.send('reindex_articles', task_id=...)
  → return 202 + task_id
  
[separate worker process]
@dramatiq.actor
def reindex_articles(task_id):
  repo.mark_running(task_id)
  try: indexer.reindex_all_articles(...)
  except: repo.mark_failed(...)
  repo.mark_completed(...)
```

**Pros:**
- Production-grade reliability: retry-with-backoff, dead-letter,
  multiple worker replicas, no in-process blocking.
- Pluggable: RabbitMQ / Stub broker для тестов (deterministic, no
  Redis container).
- Stateless workers — easy horizontal scale.
- Crash recovery: worker dies → task stays in queue, picked up by
  next worker.

**Cons:**
- New external service (Redis) — infra cost, monitoring, backup.
- Operationally Redis = single point of failure (or HA = more cost).
- Two deploy artifacts (gateway + worker) — minor complexity.
- Dramatiq Python library = новая зависимость + transitive deps.

**ФЗ-152 implications:**
- Redis RAM может содержать task payloads (audit-log export filters,
  reindex scope). Не PII по design (см. allowlist в task params),
  но Redis должен быть в РФ.
- Logging discipline: Dramatiq logs включают actor name + args; не
  должны включать ПДн (audited через unit test).

### Вариант B — Pure asyncio.create_task (no new service)

**Pipeline:**
```
POST /admin/reindex
  → repo.create(type='reindex', status='PENDING')
  → asyncio.create_task(_execute_reindex(task_id))
  → return 202 + task_id (immediately)

async def _execute_reindex(task_id):
  # Runs in same process, off-request event loop.
  ...
```

**Pros:**
- No new service.
- Re-uses pattern from webhook worker (ADR-0010 #174).
- Простой mental model: one process.
- No Redis cost.

**Cons:**
- **Crash recovery**: app restart → in-flight tasks pissapere. Mitigation:
  startup hook scans `admin_tasks WHERE status IN ('PENDING', 'RUNNING')
  AND created_at < now() - INTERVAL '15 min'` → mark FAILED with
  reason `"restarted before completion"`.
- **No retry**: failure = FAILED, no automatic re-run. Mitigation: caller
  re-POST'ает.
- **No horizontal scale**: tasks run on single gateway pod. Production
  for reindex с 1M articles needs split.
- **Resource pressure**: heavy CPU/IO task в gateway process degrades
  HTTP latency для other endpoints. Mitigation: rate-limit task
  spawns; serialize same-type tasks.

**Crash recovery test plan:**
- Unit: `_reaper_orphaned_tasks(session)` ставит FAILED rows с stale
  RUNNING status.
- Integration: spawn task, kill process, restart, verify reaper marks
  it FAILED.

### Вариант C — APScheduler in-process (single-shot delayed)

Не рассматриваем серьёзно: APScheduler — cron-style scheduling, не task
queue. Не имеет retry / dead-letter / horizontal scale. Хуже B по всем
осям.

## Рекомендация

**Вариант B на текущий dev/MVP scale → Вариант A на production-scale.**

Аргументация:
- На текущих волумах (10s of articles, 5-pair smoke eval) sync execution
  работает. asyncio.create_task сразу убирает блокировку HTTP request'а
  без infra cost.
- Reaper + retry-on-resubmit covers MVP reliability needs.
- Когда landit real LLM creds + 200-pair golden dataset (CS.11 backlog),
  Вариант A нужен (eval может занять часы, нужен retry + monitoring).
- Switch B → A: API surface не меняется (admin_tasks table + endpoints
  identical), только execution layer.

## Открытые вопросы для Архитектора

1. **Approve Вариант B или сразу A?** B быстрее ship'ится но потребует
   second migration позже. A требует Redis в production infra сейчас.
2. **Если B: какой reaper window?** 15 min default разумно? Или нужен
   per-task-type SLA (reindex 60min, export 10min, eval 6h)?
3. **Если A: какой broker?**
   - Redis (recommended; уже знакомый stack)
   - RabbitMQ (more features, more infra)
   - Stub-only для CI tests
4. **Один worker pod или горизонтальный scale?** Если A — обычно
   2-3 replicas для HA.
5. **Worker metrics:** scope какие нужны? `kb_admin_task_duration_seconds
   {type}`, `kb_admin_task_completed_total{type, status}` минимум?
6. **Rate-limit same-type tasks?** Например только 1 reindex в run одновременно
   (worth не пересоздавать embeddings 2x параллельно).

## Implementation gating

PR с реализацией создаётся ТОЛЬКО ПОСЛЕ ADR approve. Если выбран
Вариант B — implementation добавляет:
- `src/api/admin/task_runner.py` с asyncio.create_task spawning.
- `src/api/admin/task_reaper.py` startup hook + tests.
- Update operational_router + audit_log_router + eval_runs_service:
  inline execution → spawn task.

Если Вариант A — additionally:
- `requirements.txt` Dramatiq + redis pins.
- `infra/docker-compose.yml` Redis service.
- `src/workers/admin_tasks/` package с actors per task type.
- Deploy artifact (worker container).
