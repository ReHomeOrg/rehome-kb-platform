# ADR-0011: kb-vault — менеджер паролей с zero-knowledge архитектурой

## Статус

- [ ] **Принято**
- [x] Предложено
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-14
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласование Архитектора:** ожидается

## Контекст

PZ §8 «Менеджер паролей, доступы, IT-активы» — самый чувствительный
раздел внутренней базы знаний. Требования:

- Корпоративный vault для секретов (SSH-ключи, пароли БД, API-ключи,
  банковские кабинеты, КЭП-токены, и т.д.).
- AES-256 шифрование at rest.
- Master password + обязательная 2FA (TOTP / FIDO2).
- Группы доступа по командам + per-secret access groups.
- Audit log каждого read / copy / edit.
- Ротация: API-ключи 90 дней, user passwords 180 дней.
- Размещение на инфраструктуре reHome в РФ (ФЗ-152).
- Категория A из ПЗ §1.4 — «разрабатываем сами», не используем
  Bitwarden / 1Password / Vaultwarden.

Платформа — kb-platform — уже имеет SSO через Keycloak, audit_log table
(#102), RBAC через access_level (ADR-0003). Vault строится поверх этих
примитивов.

## Решение

**kb-vault реализуется как zero-knowledge (E2EE) хранилище секретов**:
сервер хранит зашифрованные blob'ы, не имея ключа для их расшифровки.
Шифрование/дешифрование — целиком на клиенте.

### Принципы

1. **Zero-knowledge**: сервер никогда не видит plaintext секретов и не
   имеет master password / derived keys. Компрометация storage layer не
   приводит к утечке секретов (только к недоступности).

2. **Client-side crypto**: pure JavaScript / WASM в браузере (через
   WebCrypto API) + matching CLI client (опционально, в Stage 2). Сервер
   — opaque storage с metadata.

3. **Master password не хранится**: используется только клиентом для
   деривации vault key (Argon2id). На сервер передаётся только
   `vault_auth_hash` (отдельный отрезок hash chain) для аутентификации,
   не для расшифровки.

4. **Per-secret encryption**: каждый секрет шифруется отдельным AES-256-GCM
   ключом с уникальным IV. Per-secret keys обёрнуты vault master key
   пользователя.

5. **Group sharing — асимметричное**: каждая access group имеет
   keypair (X25519). Per-secret key обёрнут публичными ключами всех
   участников группы (`sealed_box`-style). Добавление участника =
   re-wrap всех existing secrets группы под новый pubkey.

6. **Audit log — внешний к шифрованию**: все операции (read / copy /
   edit / share) пишутся в существующую `audit_log` table с
   `resource='vault_secret'`. Plaintext payload в audit нет — только
   metadata (secret_id, actor, IP, timestamp, action).

### Архитектура

```
┌─────────────┐    encrypted blobs    ┌──────────────┐
│   Browser   │ ◄───── HTTPS ────────►│  kb-platform │
│  (WebCrypto)│                       │   gateway    │
└─────────────┘                       └──────┬───────┘
       │                                     │
       │ derives:                            ▼
       │  - vault_master_key (Argon2id)  ┌──────────┐
       │  - vault_auth_hash              │ Postgres │
       │ encrypts:                       │  vault_* │
       │  - per_secret_key (AES-256-GCM) │  tables  │
       │  - wrapped by master/group      └──────────┘
       └─────────────────────────────────────────────┘
```

### Crypto specification

**Key derivation (Argon2id)**:
- Memory: 64 MiB
- Iterations: 3
- Parallelism: 4
- Salt: 16 random bytes per user (stored server-side, opaque)
- Output: 32-byte key

**Vault key derivation** (single Argon2id call → splits via HKDF):
- `master_key = Argon2id(master_password, salt)`
- `vault_key = HKDF-SHA256(master_key, info='vault-encrypt', len=32)`
- `auth_hash = HKDF-SHA256(master_key, info='vault-auth', len=32)`

`auth_hash` sent to server for login; `vault_key` stays client-side.

**Per-secret encryption**:
- Generate random `secret_key` (32 bytes) per secret.
- `ciphertext = AES-256-GCM(secret_key, plaintext, IV=random_12_bytes)`
- Server stores: `iv || ciphertext || tag` (variable-length blob).

**Master/group wrapping**:
- Personal: `wrapped = AES-256-GCM(vault_key, secret_key, IV=random)`.
- Group: для каждого участника group g `wrapped_g = X25519_seal(g.pubkey, secret_key)`.

**Group keypair**:
- X25519 (Curve25519). Каждый user — own keypair stored client-side
  encrypted under `vault_key`. Public key — server-visible.

### Доменная модель (server-side)

```
vault_users (extension к keycloak users)
  user_id (UUID, FK keycloak)
  argon_salt (BYTEA, 16 bytes)
  auth_hash (BYTEA, 32 bytes)
  encrypted_x25519_privkey (BYTEA) -- wrapped under vault_key
  x25519_pubkey (BYTEA)
  totp_secret_encrypted (BYTEA, NULL until 2FA setup) -- wrapped under vault_key
  created_at, updated_at, last_unlock_at

vault_groups
  id (UUID PK)
  name (TEXT)
  description (TEXT)
  created_by (user_id)
  created_at

vault_group_members
  group_id (FK)
  user_id (FK)
  role (TEXT: 'owner', 'member')
  added_at

vault_secrets
  id (UUID PK)
  title_ciphertext (BYTEA) -- даже title зашифрован (zero-knowledge)
  category (TEXT, plaintext — для filter/group only; не sensitive)
  owner_id (user_id) -- кто отвечает за актуальность
  created_at, updated_at
  expires_at (timestamp NULL) -- для ротационных reminders
  archived_at (timestamp NULL)

vault_secret_wraps -- per-recipient encrypted secret keys
  secret_id (FK)
  -- exactly one of (user_id, group_id) set:
  user_id (FK NULL)
  group_id (FK NULL)
  wrapped_key (BYTEA) -- secret_key wrapped under user.vault_key OR group.pubkey
  PRIMARY KEY (secret_id, user_id, group_id)

vault_secret_blobs -- the actual encrypted payload
  secret_id (FK PK)
  ciphertext (BYTEA) -- {iv || encrypted_payload || tag}
  payload_version INTEGER -- monotonic для concurrent-edit detection

-- audit_log table (existing #102) — все операции:
-- action ∈ {vault.unlock, vault.secret.read, vault.secret.created,
--           vault.secret.updated, vault.secret.deleted, vault.share.added,
--           vault.share.revoked}
```

### Authentication flow

1. Login через SSO (Keycloak) → JWT с `vault_enabled` claim.
2. **Unlock**: клиент prompts master password.
3. `master_key = Argon2id(password, server_returned_salt)`.
4. `auth_hash = HKDF(master_key, 'vault-auth')`.
5. POST `/vault/unlock {auth_hash}` → server compares to stored hash →
   200 + `unlock_session_token` (short-lived 15min) ИЛИ 401.
6. Все vault API calls используют `unlock_session_token` поверх обычного
   Keycloak JWT.

**2FA enforcement**:
- TOTP secret хранится encrypted under `vault_key` (zero-knowledge).
- Перед `/vault/unlock` finalize'ом — challenge: клиент посчитал TOTP
  локально, server проверил hash chain (см. подробно в spec).

### Audit log

Каждое:
- `unlock` (успешный / failed) — обязательно (anti-brute-force trail).
- `secret.read` — даже metadata read'ы (за исключением `list` — иначе
  объём логов взорвётся).
- `secret.created` / `updated` / `deleted`.
- `share.added` / `revoked`.

Запись:
```
{
  actor_user_id, ip, timestamp,
  action='vault.secret.read',
  resource='vault_secret',
  resource_id=<secret_id>,
  metadata={title_blob_size, secret_age_days}  -- НИКАКОГО plaintext
}
```

### Rotation reminders

`vault_secrets.expires_at` — настраивается клиентом. Background worker
(daily) собирает expired/expiring records, отправляет notification
владельцу (email/in-app). Notification содержит только `secret_id` и
title hint — НЕ plaintext.

## Альтернативы

1. **Server-side encryption (server владеет key)** — отклонена. Не
   соответствует требованию zero-knowledge; компрометация сервера =
   утечка всех секретов. PZ §8 явно требует ИБ-уровень соответствующий
   корпоративному vault'у.

2. **Bitwarden / Vaultwarden self-hosted** — отклонена PZ §1.4 (категория
   A, разрабатываем сами). Контр-аргументы: (a) external dep с регулярными
   updates / CVE, (b) compliance audit'ы под reHome нужно отдельно.

3. **Hardware-backed (HSM, YubiHSM)** — рассматривалась. Преимущества:
   master key никогда не покидает HSM. Недостатки: (a) HSM добавляет
   single point of failure, (b) cost + procurement, (c) client-side
   crypto это не отменяет (zero-knowledge всё равно требует client keys).
   **Hybrid возможен в Stage 2**: HSM для server-side key wrapping (защита
   от offline DB dump). Не блокирует Stage 1.

4. **JS browser crypto без WASM** — рассматривалось. WebCrypto API
   достаточно для AES-GCM + ECDH; Argon2id требует WASM lib (вне
   WebCrypto). Зависимость от WASM acceptable (libsodium.js, argon2-browser).

5. **Native mobile/desktop клиенты** — defer. MVP — только browser.
   Mobile может быть PWA Stage 2; native — Stage 3+ (если бизнес-кейс).

## Последствия

### Положительные

- Compromise серверной DB = encrypted blobs only; secrets safe.
- Compliance-friendly: ФЗ-152 + ISO 27001 / SOC2 vault patterns.
- Group sharing без single shared password.
- Audit log без plaintext leak (metadata only).
- Master password / TOTP forgotten = lockout (acceptable — recovery
  через group emergency access, см. Stage 2).

### Отрицательные / компромиссы

- Master password lost = **all secrets lost permanently**, recovery
  невозможно без emergency access (Stage 2 фича). Это feature, не bug —
  но требует training для пользователей.
- Performance: Argon2id 64MiB/3-iter блокирует main thread ~500ms на
  типичном CPU (acceptable для unlock'а раз в 15min, painful если делать
  на каждом запросе).
- Browser-only — нет CLI / native в MVP.
- Group membership change = re-wrap secret keys для всех existing
  secrets группы (linear cost, acceptable до ~1k secrets/group).
- Lost device (с unlock_session_token) — короткое окно exposure до
  expiry. Mitigation: short TTL (15min default), revoke endpoint.

### Технические следствия

- **Frontend**: новый module kb-vault page, WebCrypto + argon2-browser
  WASM, secure DOM (no `dangerouslySetInnerHTML` для secret display;
  copy via execCommand`'copy'` или Clipboard API через user gesture).
- **Backend**: новый модуль `src/api/vault/` с моделями + endpoints.
  Zero crypto code на backend — pure storage layer.
- **Migration**: 4 новые таблицы (см. domain model выше).
- **Performance**: Argon2id memory (64MiB) пересекает min-spec mobile;
  для mobile possibly weaker params (32MiB). Decision: keep 64MiB,
  warn пользователя на low-RAM devices.
- **Backup**: encrypted blobs backuppable через стандартный pg_dump;
  recovery восстанавливает encrypted state, plaintext доступен только
  с master password.

## Открытые вопросы (отдельные follow-up'ы)

1. **Emergency access**: при увольнении сотрудника / lost master
  password — как восстановить доступ к группам? Pre-shared escrow
  ключ у CTO + второго админа (2-of-2)? Адресуется в Stage 2 ADR.

2. **Mobile clients**: PWA достаточно или нужна native app?
  Architect решит после Stage 1 launch'а.

3. **TOTP backup codes**: хранить как encrypted blob (тогда same risk
  как master password) или печатать одноразово при setup'е? Решение:
  печатать одноразово, не хранить.

4. **Hardware token (FIDO2)** support — Stage 2 (после MVP).

## Этапы внедрения

**Stage 1 — Foundation (4-6 PRs, 2-3 weeks dev)**:
1. ADR (этот файл, текущий PR).
2. Migration 0016 (4 vault tables) + ORM models.
3. Backend repository + zero-knowledge endpoints
   (`POST /vault/unlock`, `GET/POST/PUT/DELETE /vault/secrets`,
   `POST /vault/groups/{id}/members`).
4. Audit log integration.
5. Frontend page + WebCrypto + Argon2id WASM integration.
6. Group keypair generation + share/revoke UI.

**Stage 2 — Operational (TBD)**:
- Emergency access / recovery flow.
- Rotation notifications worker.
- Mobile PWA polish.
- Optional FIDO2.
- Optional HSM hybrid.

## Ссылки

- PZ §8 «Менеджер паролей, доступы, IT-активы».
- ADR-0001 (стек), ADR-0003 (access-level / RBAC), ADR-0009
  (secrets management — но это про SOPS/age для infra secrets,
  отдельно от kb-vault для пользовательских secrets).
- Audit log table (#102, PR #105).
- Argon2 RFC 9106 — параметры reference.
- libsodium / sodium-plus — WASM crypto reference.
- OWASP Application Security Verification Standard 4.0 §6.x.
