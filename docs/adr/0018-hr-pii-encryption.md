# ADR-0018: HR Stage 2 — column-level encryption ПДн сотрудников (Fernet + env-managed key)

## Статус

- [ ] Предложено
- [x] **Принято**
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-22
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** да, 2026-05-22 (вариант A — Fernet + env-managed key)

## Контекст

HR Stage 1 (#150 / migration `20260514_030000_hr_foundation.py`) landed
минимальный employee card: ФИО, должность, hire/termination dates,
JSONB `contact_info` + `notes`. ПДн поля — паспорт, ИНН, СНИЛС, банковский
счёт, КЭП-серт — **намеренно отложены** в Stage 2 (см. docstring
`hr_employees.models.py:1-9`).

Эти поля — это самые чувствительные ПДн в платформе:
- **Паспортные данные** (серия+номер, кем выдан, дата): по ФЗ-152 §10.1
  относятся к «специальной категории ПДн», требуют усиленных мер.
- **ИНН / СНИЛС**: persistent identifier, утечка → KYC fraud risk.
- **Банковский счёт**: financial fraud vector.
- **КЭП-серт**: компрометация = подделка подписи (юридические следствия).

ФЗ-152 §19 «Меры по обеспечению безопасности ПДн»:
- п.2(3): «применение прошедших процедуру оценки соответствия средств
  защиты информации» — для encryption этих категорий ПДн обязательно.
- п.2(5): «учёт носителей персональных данных» — implicit audit_log.
- Приказ ФСТЭК №21 (требования к защите ИСПДн классов K1-K4) — для
  кадровых ИСПДн (1 группа субъектов) обычно K2 → требуется криптографическая
  защита данных при хранении и передаче.

Архитектурные ограничения:
1. **ФЗ-152**: все ключи и зашифрованные данные — в РФ. Внешние KMS
   (AWS KMS, Azure Key Vault, GCP) исключены.
2. **Self-hosted bias** (CLAUDE.md): не подключать новые внешние сервисы
   без явного обоснования.
3. **kb-vault уже существует** (ADR-0011, zero-knowledge E2EE) — но это
   client-side encryption, не подходит для server-side ПДн полей где
   backend должен читать значения для UI projection / БУХ-интеграций (1С:ЗУП).
4. **Команда compact** — операционный overhead отдельного KMS (HashiCorp
   Vault / OpenBao / Yandex Lockbox) сейчас несоразмерен.
5. **0 production rows** — HR Stage 1 не наполнялась реальными данными,
   no backfill migration needed.

## Решение

**Application-level Fernet symmetric encryption + env-managed
key (single rotation key, future migration на KMS — backlog).**

### Принципы

1. **Field-level encryption на 4 ПДн колонках** `hr_employees`:
   `passport_number_encrypted`, `inn_encrypted`, `snils_encrypted`,
   `bank_account_encrypted` — все `BYTEA NULLABLE` (nullable = «не
   заполнено», не «зашифровано пустое»).

2. **Fernet (cryptography lib)** — symmetric AES-128-CBC + HMAC-SHA256.
   Уже в `requirements.txt` (косвенно — через `cryptography>=42.0`,
   используется auth модулем для JWT verification).

3. **Key из env var `HR_ENCRYPTION_KEY`** — 32-byte url-safe base64
   string (`Fernet.generate_key()`). Не хранится в БД, не logging'уется,
   передаётся через secret-management слой (см. ADR-0009 — env vars
   + SOPS-encrypted at rest).

4. **Encryption/decryption helpers** в `src/api/hr/crypto.py`:
   ```python
   def encrypt_pii(plaintext: str | None) -> bytes | None: ...
   def decrypt_pii(ciphertext: bytes | None) -> str | None: ...
   ```
   None passthrough — nullable semantic preserved.

5. **Repository encrypts на insert/update, decrypts на read** —
   transparent для router'а. Frontend получает plaintext ПДн только
   когда scope = HR_RESTRICTED (staff_hr / staff_admin per ADR-0003).

6. **Pydantic projection scope-aware** — `HrEmployeeView` для
   HR_RESTRICTED включает decrypted ПДн; другие scope (staff_admin без
   HR) видят только метаданные без ПДн (masked) или 404 mask. ADR-0003
   pattern.

7. **Audit log на ПДн read** — `RESOURCE_HR_EMPLOYEE` + action
   `hr.employee.pii_accessed` записывается в audit_log при GET с decrypt.
   Compliance trail: «кто и когда смотрел паспорт user X». ФЗ-152 §19.2(5).

8. **Audit log на ПДн write** — `hr.employee.pii_updated` с
   `metadata={updated_fields: [paspport, snils, ...]}` (НЕ сами
   plaintext значения — анти-leak в audit_log).

9. **Key rotation strategy** — manual procedure:
   - Backend поддерживает `HR_ENCRYPTION_KEY_LEGACY` env (optional) —
     старый ключ для decrypt-only.
   - Migration script `python -m src.workers.hr_pii_rekey` читает все
     rows, re-encrypts с new key, atomic UPDATE.
   - После завершения `HR_ENCRYPTION_KEY_LEGACY` env удаляется.
   - Rotation policy: ежеквартально или при known leak.

10. **Backup considerations**:
    - Postgres dump содержит ciphertext + encrypted backup tooling
      (pgBackRest) — двойная защита.
    - **Ключ НЕ попадает в Postgres dump** (env-only) — backup без
      ключа useless.

### Поля и масштаб scope (PoC implementation):

| Поле | Plaintext type | Encrypted column | UI access |
|------|----------------|------------------|-----------|
| `passport_number` | "1234 567890" | BYTEA | HR_RESTRICTED |
| `inn` | "770700700007" (12 digits) | BYTEA | HR_RESTRICTED |
| `snils` | "112-233-445 95" | BYTEA | HR_RESTRICTED |
| `bank_account` | "40817810099910004312" | BYTEA | HR_RESTRICTED |

КЭП-серт path / passport_scan binary — отдельный flow через
`kb-files` (ADR-0012, MinIO с server-side encryption). НЕ часть этого ADR.

## Альтернативы

1. **B. Postgres `pgcrypto` extension + `pgp_sym_encrypt`** — отклонена.
   - Pro: encryption происходит на DB уровне, ключ передаётся в каждом
     запросе (либо через `SET LOCAL pgcrypto.key`).
   - Pro: лучшая интеграция с SQL queries (можно искать по encrypted
     полям через индекс хешей).
   - Con: ключ периодически появляется в Postgres logs (если query
     logging включён) — security risk.
   - Con: ключ на DB-уровне → admin DBA имеет доступ → расширяется
     attack surface.
   - Con: rotation требует full table scan via SQL DDL.
   - Con: pgcrypto — Postgres extension, может быть не enabled в managed
     PostgreSQL.

2. **C. Yandex Lockbox / Sber KMS integration** — отклонена для MVP.
   - Pro: enterprise-grade key management, automated rotation, KMS API.
   - Pro: ФЗ-152 compliant (RU data center).
   - Con: новая внешняя зависимость, противоречит CLAUDE.md «разрабатываем
     сами»-bias.
   - Con: bootstrap-stage overhead — KMS authentication, IAM, billing.
   - Con: vendor lock-in.
   - **Не закрываем дверь** — этот ADR explicitly предусматривает
     migration path к KMS, когда количество ключей / частота ротации это
     оправдает (см. §«Key rotation strategy»).

3. **D. kb-vault (ADR-0011) для ПДн** — отклонена.
   - Pro: уже работает, audit log есть, zero-knowledge.
   - Con: kb-vault — client-side encryption (E2EE), сервер не имеет
     plaintext. Для HR backend нужен server-side decrypt (для 1С:ЗУП
     export, UI projection, печатных форм).
   - Con: vault — для admin secrets, не для bulk per-row ПДн.

4. **E. Tablespace-level / disk-level encryption** (LUKS / Postgres TDE) —
   отклонена как единственная мера.
   - Pro: prevents physical disk theft scenarios.
   - Con: backup'ы расшифрованы. Application-level dump (pg_dump) — тоже
     plaintext. Не отвечает на «как защитить от компрометации backup'а».
   - Used **дополнительно** в production (defence-in-depth), но не как
     primary защита поле-level ПДн.

5. **F. Не encrypt'ить — полагаться на ADR-0003 access_level + ФЗ-152 §19
   организационных мер** — отклонена.
   - Не соответствует Приказу ФСТЭК №21 для K2 ИСПДн.
   - При компрометации Postgres → все ПДн в plaintext.

## Последствия

### Положительные

- **ФЗ-152 §19 + ФСТЭК K2 compliance** для HR-модуля без подключения
  внешних KMS.
- **Defence-in-depth**: backup encryption (pgBackRest) + field encryption
  (Fernet) + access_level (ADR-0003) — 3 независимых слоя.
- **Простой rollback path**: если architect позже выберет другую crypto
  стратегию, миграция = re-encrypt rows + drop env var.
- **Локальный dev unchanged**: dev key (`FERNET_KEY=local-dev-key`) — не
  блокирует разработку.
- **Migration path к KMS**: encrypt/decrypt в `hr/crypto.py` — единая
  точка замены на KMS API call'ы (Yandex Lockbox / Sber KMS / OpenBao).

### Отрицательные / компромиссы

- **Manual key rotation** — без automated KMS quarter'ная ротация —
  ручной runbook (см. §«Key rotation strategy»). Risk: пропустить
  rotation window.
- **Env-key leak = ПДн compromise** — если env file / k8s secret leak'нет,
  attacker может decrypt все rows. Mitigation: SOPS encryption at rest
  (ADR-0009) + audit_log access.
- **Single key для всех rows** — нельзя revoke access одному employee
  без re-encrypt всей таблицы. Per-row keys — overengineering для < 100
  employees.
- **Нет PII search by exact match** — нельзя `WHERE inn = '770...'` для
  lookup'а сотрудника. Workarounds: blind index (HMAC over `inn` →
  bytea search column) — backlog. Lookup'ы admin UI идут через `id` /
  `user_id` / `personnel_number` (unencrypted unique identifiers).
- **Ключ-only backup useless** — но это и invariant'ом является. Если
  забыли ключ → данные не recoverable. Mitigation: ключ хранится в SOPS
  + offline backup в physical safe.

### Технические следствия

- **Новая миграция**: `add_hr_pii_columns` (`passport_number_encrypted`,
  `inn_encrypted`, `snils_encrypted`, `bank_account_encrypted` — BYTEA
  nullable).
- **Новые модуль**: `src/api/hr/crypto.py` с `encrypt_pii` / `decrypt_pii`
  helpers + module-level Fernet instance из `Settings.hr_encryption_key`.
- **Settings extension**: `hr_encryption_key: str` (required env), с
  validation что это valid Fernet key на startup (fail-fast). Optional
  `hr_encryption_key_legacy: str | None` для rotation.
- **Repository extension**: `HrEmployeeRepository.create/update` — auto-encrypt;
  `get_by_id / list` — auto-decrypt. Transparent.
- **Schema extension**: `HrEmployeeView` для HR_RESTRICTED — decrypted
  ПДн; otherwise — empty / masked.
- **Audit actions**: `hr.employee.pii_accessed`, `hr.employee.pii_updated`.
- **Тесты**: encrypt/decrypt roundtrip + scope-based visibility + audit
  trail + key rotation worker.
- **Documentation**: README «Переменные окружения» — добавить
  `HR_ENCRYPTION_KEY` (required) + generate-key инструкция.

### Риски

- **Risk 1**: forgotten key generation в production → app fails to start
  (fail-fast Settings validation). **Mitigation**: deploy runbook +
  health-check.
- **Risk 2**: dev key reuse в production. **Mitigation**: explicit
  check `if env != 'dev' and key starts with 'local-'` → ValueError.
- **Risk 3**: ciphertext в Postgres logs (CSV-exporter / SQL trace).
  **Mitigation**: logs config — exclude `hr_employees` table queries +
  ciphertext = BYTEA (Postgres logs escape binary).
- **Risk 4**: PoC scope creep — кто-то добавит ещё encrypted columns без
  ADR amendment. **Mitigation**: explicit table в §«Поля» —
  amendment-required для extension.

### Production readiness gates (требуется ДО включения key в production)

1. SOPS encryption at rest для production env file (ADR-0009 alignment).
2. Backup procedure: ключ хранится в **отдельном** secure storage
   (physical safe + offline copy).
3. Documented runbook: «key rotation», «key recovery», «forensic
   incident response».
4. Compliance assessment: соответствует Приказу ФСТЭК №21 K2 — внешний
   audit (по requirements).

## Ссылки

- ПЗ: §7 (HR-модуль), §1.4 (категория A — «разрабатываем сами»)
- ТЗ: §3.13 (HR endpoints), §4.3 (access tiers), §6.2 (ФЗ-152)
- Связанные ADR:
  - ADR-0003 (knowledge-base tiers + scope mapping)
  - ADR-0009 (secrets management — env + SOPS)
  - ADR-0011 (vault zero-knowledge crypto)
  - ADR-0012 (documents object storage — MinIO server-side encryption)
- Внешние материалы:
  - ФЗ-152 §19 «Меры по обеспечению безопасности ПДн»
  - Приказ ФСТЭК №21 (требования к защите ИСПДн K1-K4)
  - [Fernet spec](https://github.com/fernet/spec/blob/master/Spec.md)
  - [`cryptography` library docs](https://cryptography.io/en/latest/fernet/)
