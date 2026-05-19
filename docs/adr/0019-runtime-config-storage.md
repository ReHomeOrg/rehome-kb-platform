# ADR-0019: Writable runtime config storage (system_config + Settings merge layer)

## Статус

- [ ] Предложено
- [x] **Принято**
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-23
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** да, 2026-05-23 (Вариант A — Single JSONB
  row + Settings merge layer + allowlist + X-MFA-Token honest stub до
  Keycloak step-up landing'а).

## Контекст

OpenAPI 04 определяет 2 endpoint'а для runtime мутации админ-конфига,
которые в текущем коде остаются unimplemented:

| Endpoint | Назначение |
|---|---|
| `PATCH /api/v1/admin/system-config` (updateSystemConfig) | Изменить feature_flags / LLM config / moderation thresholds / webhook delivery params без redeploy. |
| `PUT /api/v1/admin/llm/active` (setActiveLlmProvider) | Переключить активного LLM-провайдера (по сути — конкретный case PATCH'а). |

`GET /admin/system-config` уже landит (#229) — read-only projection
из `Settings`. PATCH-сторона требует:
- Persistent storage для мутируемых значений (после restart'а сервиса
  изменения должны сохраняться).
- Безопасный merge: env-конфиг остаётся primary source-of-truth;
  DB overlays только для явно allowlist'ленных keys.
- MFA validation per OpenAPI (PUT /admin/llm/active требует
  `X-MFA-Token` header).

Без этого design'а PATCH/PUT — реальный security/reliability risk:
- Любой staff_admin сможет менять кардинальные настройки (LLM_PROVIDER,
  moderation thresholds) без 2nd factor.
- Без allowlist — потенциальное privilege escalation (изменить scope
  правил доступа через DB).
- Без reload semantics — изменения вступят в силу только после
  restart'а (бессмысленный feature).

Архитектурные ограничения:
1. **CLAUDE.md §6** — нельзя подключать новые external сервисы без
   ADR'а. system_config — internal DB table, не внешняя зависимость, OK.
2. **ADR-0018 + ФЗ-152**: encryption keys / Vault creds / paspport
   passwords НИКОГДА не должны быть в system_config (их место — env+SOPS).
3. **ADR-0007 Keycloak realm structure** — MFA для admin-операций уже
   обозначен как step-up auth через Keycloak (acr_values=2). Реализация
   step-up — backlog отдельный.

## Альтернативы

### Вариант A — Single JSONB row (рекомендуется)

Единая таблица `system_config` с одной row `id=1`, JSONB-колонка `data`:

```sql
CREATE TABLE system_config (
    id            int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    data          jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    updated_by    text NOT NULL
);
INSERT INTO system_config (id, data, updated_by) VALUES (1, '{}', 'system_init');
```

Преимущества:
- Atomic update — простой UPDATE-SET, без race condition'ов.
- Strict allowlist — backend держит `_MUTABLE_KEYS: frozenset[str]`
  (например `{"llm_provider", "moderation.auto_publish_threshold",
  "feature_flags.rag_enabled"}`); patch отбрасывает unknown keys.
- Settings merge: `Settings()` reads env как primary, затем overlays
  только allow-list keys из DB. Незнакомые keys в DB игнорируются.
- Audit trail — каждый PATCH создаёт audit_log запись с before/after.

Минусы:
- Нет history (только current state). Acceptable: audit_log хранит full
  change log + 5-year retention.

### Вариант B — Key/value rows

```sql
CREATE TABLE system_config_kv (
    key text PRIMARY KEY,
    value jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL
);
```

Преимущества:
- Простой select по key.
- Granular row-level locks.

Минусы:
- Atomicity сложнее (multi-key transaction нужна).
- Migration в Вариант A потом нетривиальна.

### Вариант C — env-only mutation (отклонено)

«Меняй env vars + restart» — но это превращает PATCH в noop с точки
зрения API. Не реализует OpenAPI contract.

## Решение

**Рекомендуется Вариант A** (single JSONB row).

### Файлы / модули

1. **Migration** `0024_system_config.py`:
   - Создаёт таблицу с `id=1` row insert'ом.
   - Revises → `0024_admin_tasks` (chain after eval-runs).

2. **Model** `src/api/admin/system_config_models.py`:
   - `SystemConfigRow` SQLAlchemy mapped class.

3. **Repository** `src/api/admin/system_config_repository.py`:
   - `read() → dict[str, Any]` — current overlay snapshot.
   - `patch(updates: dict[str, Any], *, actor_sub: str)` — atomic UPDATE,
     filters via `_MUTABLE_KEYS`, raises `UnknownKeyError` on unknown,
     emits audit row.

4. **Merge layer** `src/api/admin/system_config.py` (расширение
   существующего):
   - `build_system_config(settings, overlay)` теперь принимает optional
     `overlay: dict` и пересчитывает projection с overlay поверх env.
   - `get_system_config(settings, repo)` Depends-factory — читает repo,
     передаёт overlay в builder.

5. **Router** обновляется:
   - PATCH `/admin/system-config` — body validation per OpenAPI,
     X-MFA-Token header required, calls repo.patch, returns 200 + updated
     SystemConfig.
   - PUT `/admin/llm/active` — body `{provider_id, reason}`, X-MFA-Token
     required, internally PATCH'ит key `llm_provider`.

### Allowlist (initial)

Initially мутируемые keys (расширяется по мере того как UI добавляет
controls):

```python
_MUTABLE_KEYS: frozenset[str] = frozenset({
    # LLM
    "llm_provider",          # PUT /admin/llm/active short-hand
    "llm_fallback_provider",
    # Moderation
    "moderation.auto_publish_threshold",
    "moderation.require_review_for_categories",
    # Feature flags
    "feature_flags.rag_enabled",
    "feature_flags.webhook_worker_enabled",
})
```

Allowlist охватывает только endpoint surface ТЗ; secrets (Vault keys,
JWT secret, DB passwords) НИКОГДА не в этом списке.

### X-MFA-Token validation

**MVP:** header принимается, value записывается в audit_log metadata.
**Real validation** — backlog (нужен Keycloak step-up flow integration:
caller получает `acr=2` token через `/protocol/openid-connect/auth?
acr_values=2`, мы validate'им `acr` claim в `require_step_up_auth`
dependency).

В MVP без validation endpoint — `request authenticated + audited
without 2nd-factor enforcement`. Это honest stub с явной marker'кой
`x-implementation-note` в OpenAPI.

### Reload semantics

Settings cache per-request (через `Depends(get_settings)` — singleton
из `lru_cache`). Когда PATCH меняет DB:
- В рамках того же request'а — caller уже committed change, get_settings
  не affected.
- Subsequent requests — `get_system_config` dependency читает DB overlay
  свежим. Settings (env) — singleton, не меняется.
- Workers (popular_query, vault_reminders) — используют `Settings` для
  feature_flags; они НЕ читают DB overlay (acceptable: рестарт worker'а
  на feature_flag change приемлемая trade-off за simpler model).

Если нужен hot-reload для workers — backlog (нужен LISTEN/NOTIFY +
local cache invalidation).

## Открытые вопросы для Архитектора

1. **Approve Вариант A** или предпочитаете B / альтернативный design?
2. **Allowlist scope** — какие keys реально нужны admin UI сейчас?
   Может ли начать с минимума (`llm_provider` only) и расширять
   itera tively?
3. **X-MFA-Token validation** — приоритет?
   - Honest stub в MVP (audit-trail без crypto verification).
   - Block PR до landing'а Keycloak step-up?
4. **Worker reload** — workers перечитывают конфиг при PATCH или нет?
   Простой ответ: «нет, рестарт после critical change'а» — acceptable?
5. **History / undo** — нужна или audit_log достаточен?

## Implementation gating

PR с реализацией создаётся ТОЛЬКО ПОСЛЕ ADR approve. Без approve'а —
рассматривается как design-violation per CLAUDE.md §9 (deviation from
OpenAPI implementation требует письменного approve).
