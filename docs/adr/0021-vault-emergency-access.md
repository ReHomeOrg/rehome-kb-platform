# ADR-0021: Vault Stage 2 — emergency access (2-of-2 escrow)

## Статус

- [x] **Предложено**
- [ ] Принято
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-23
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Требуется approve Архитектора:** выбор Варианта (A / B / C) + escrow
  политика (M-of-N threshold + восстановление SLA).

## Контекст

Vault Stage 1 (ADR-0011 + landed implementation) построен на zero-
knowledge model: master password выводит KEK (key-encryption key)
через Argon2id на клиенте → DEK'и шифруют секреты → backend хранит
только ciphertext + wraps. Если user забывает master password, или
если key user покидает компанию unexpectedly, **доступ к его секретам
теряется навсегда** — это explicit design choice ADR-0011.

Однако production требует **emergency access** для:

1. **Key person leaves / incapacitated** — компания должна восстановить
   business-critical credentials (банковские кабинеты, КЭП, расчётные
   счета) даже если user недоступен.
2. **ФЗ-152 §17.1 — security incidents** — при подозрении breach
   директор может потребовать access к user's vault для forensic
   review.
3. **Юридический запрос РКН / суд** — оператор обязан предоставить
   данные при наличии legal order.

ADR-0011 §"Emergency access" upon Stage 2:
> «Раздельное хранение: ⅔-of-N escrow protocol — split key между
> minimum 2 doverenny licami (например, директор + юрист). Восстановление
> ТОЛЬКО при coincidence обоих»

Stage 2 design — это документ.

Архитектурные ограничения:
1. **ФЗ-152**: все ключевые материалы — в РФ. Escrow shares — на
   отдельных носителях (физ. сейфы / printed envelopes).
2. **Никакого backdoor для backend**: emergency access не должен
   позволять любому единичному staff (даже staff_admin) decrypt'ить
   vault unilaterally. Иначе zero-knowledge ломается.
3. **Audit trail**: каждое emergency unlock — explicit log entry с
   reasoning (incident_id / legal_order_id / departure_case_id),
   тригерит security_incident автоматически.
4. **CLAUDE.md §6** — не подключать external services без ADR. Все
   варианты ниже — self-hosted/in-process.

## Альтернативы

### Вариант A — Shamir Secret Sharing 2-of-2 (recommended baseline)

**Stack:** Python [secretsharing](https://github.com/blockstack/secret-sharing)
или native impl Shamir SSS over GF(2^8) для 32-byte share size.

**Setup ceremony (per user, on vault creation):**
1. User создаёт vault, derives KEK через Argon2id (как сейчас).
2. Client генерит auxiliary `escrow_key` (random 256-bit).
3. Re-wraps KEK через `escrow_key` → `KEK_escrow_ciphertext`. Stored
   в `vault_user.escrow_wrap` column.
4. `escrow_key` splits на 2 shares (Shamir 2-of-2):
   - Share1 → printed envelope, держит **директор** (физ. сейф офиса).
   - Share2 → printed envelope, держит **юрист** (физ. сейф юр.фирмы).
5. Originals shares **никогда не возвращаются** на backend / в client
   memory после ceremony.

**Recovery ceremony:**
1. Trigger: incident report / legal order / leave case.
2. Director + Lawyer **физически встречаются**, объединяют shares,
   reconstruct `escrow_key`.
3. Один из них manually вводит reconstructed key в emergency UI
   (`/admin/vault/emergency-unlock?user_id=X`).
4. Backend: unwrap `KEK_escrow_ciphertext` через `escrow_key` → KEK
   → unwrap secrets → display.
5. **Each unlock audit'ится** с `vault.emergency.unlock` action +
   security_incident row (severity=high, requires РКН notification
   per ADR-0018).

**Pros:**
- True 2-of-2: backend cannot unilaterally unlock (нет access к
  combined shares).
- Pure crypto: Shamir SSS doesn't need infra (no HSM, no KMS).
- Compliance-clean: 2 humans + physical envelopes — auditable, hard
  to compromise silently.
- ADR-0011 §«Emergency access» literally describes this approach.

**Cons:**
- **Recovery latency**: requires both humans physically present.
  Не подходит для 24h security incidents (РКН §17.1 deadline).
- **Share loss = unlocking impossible**: если оба envelopes теряются
  (пожар, человек умирает с unknown share location) — vault navсегда.
  Mitigation: 3-of-5 threshold с overlapping holders (см. Вариант B).
- **Manual share entry**: humans мерсят envelope text в UI — typing
  errors. Mitigation: integrity check (checksum suffix).

### Вариант B — Shamir 3-of-5 (more robust)

5 share holders (директор, юрист, CTO, оператор, главбух); любые 3
могут recover.

**Pros над A:**
- Tolerates loss of up to 2 shares.
- Faster recovery — не all-or-nothing waiting на одного person.

**Cons над A:**
- 5 share ceremony требует более сложной distribution.
- Сложнее audit (нужно tracker which 3 of 5 participated).
- Increases attack surface: 3 conspiring holders могут unlock без
  director knowledge.

### Вариант C — Hardware Security Module (HSM) + key escrow service

Encrypted KEK_escrow + hardware-protected master key на HSM-устройстве.
Recovery — через HSM unlock ceremony.

**Pros:**
- Hardware-protected master key (FIPS 140-2 Level 3+).
- Audit logs встроены в HSM.
- Threshold можно делать в HSM firmware.

**Cons:**
- **NEW SERVICE** — HSM hardware (Yubico HSM2 / Thales / SafeNet) =
  CAPEX + ops. Per CLAUDE.md §6 требует ADR + approve.
- HSM = single point of failure. HA cluster дорого.
- РФ HSM — ограниченный выбор сертифицированных моделей (ФСТЭК),
  цена sky-high.
- Сложнее operationally (firmware updates, slot management).

Не рекомендуется для MVP — overkill.

## Рекомендация

**Вариант A (Shamir 2-of-2) для Stage 2 MVP.**

Аргументация:
- Strict zero-knowledge сохранён.
- Минимальный infra-impact (pure-Python crypto).
- ADR-0011 §«Emergency access» literally specifies этот подход.
- Recovery latency (24h+) acceptable для majority cases (departures,
  legal orders). Для emergency incident (§17.1) — security_incident
  flow создаёт parallel investigation track.

**Future upgrade path:** если operational learning показывает что 2-of-2
блокируется reliability (lost envelope rate > 1%), migrate to 3-of-5
(Вариант B).

## Implementation scope (если A approved)

**Backend:**
1. Migration `0025_vault_emergency_access`:
   - `vault_users.escrow_wrap` column (bytea, nullable до ceremony).
   - `vault_emergency_unlock_log` table (id, user_id, requested_by,
     reason_category, reason_text, security_incident_id, unlocked_at).
2. SSS implementation: `src/api/vault/escrow.py` с `split_share` /
   `combine_shares` + tests.
3. New endpoints:
   - `POST /api/v1/vault/setup-escrow` — initiates share generation
     (returns shares в response, only at ceremony time). RBAC: vault
     owner only.
   - `POST /api/v1/admin/vault/emergency-unlock` — director + lawyer
     combine shares, vault decrypted, audit row + security_incident
     created. RBAC: staff_admin + LEGAL scope.

**Frontend:**
- `/vault/setup-escrow` — печатные envelopes для офицеров.
- `/admin/vault/emergency-unlock` — paste 2 shares + reason form.

**Audit / Compliance:**
- `vault.emergency.unlock` audit action.
- Auto-create security_incident (severity=high, type=emergency_access).
- РКН notification flag (per ФЗ-152 §17.1).

**Tests:**
- Shamir math (split-combine roundtrip, single-share rejection).
- Endpoint RBAC.
- Audit + incident creation invariants.

## Открытые вопросы для Архитектора

1. **Approve Вариант A** (2-of-2) или Вариант B (3-of-5)?
2. **Кто держит shares?**
   - Вариант A: предложение «директор + юрист» — ОК или другие
     роли (CTO, главбух)?
   - Вариант B (если выбран): кто из 5 share-holders?
3. **Recovery SLA**: 24h emergency / 72h полное снятие envelope —
   acceptable?
4. **`reason_category` enum**: предложение `incident / legal_order /
   employee_departure / forensic_audit` — нужны другие?
5. **Auto-create security_incident на каждое emergency unlock** — да?
6. **РКН notification**: каждое emergency unlock = РКН notify
   обязательно, или зависит от reason_category?

## Implementation gating

PR с реализацией создаётся ТОЛЬКО ПОСЛЕ ADR approve. Без approve'а
рассматривается как design-violation per CLAUDE.md §9.
