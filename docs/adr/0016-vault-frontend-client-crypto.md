# ADR-0016: kb-vault frontend — client-side crypto stack и декомпозиция epic'а

## Статус

[ ] Предложено
[x] Принято
[ ] Заменено ADR-MMMM
[ ] Отклонено

- **Дата:** 2026-05-17
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** да, 2026-05-17 (чат-сессия, kickoff Vault frontend epic)

## Контекст

ADR-0011 утвердил **zero-knowledge** архитектуру kb-vault: сервер хранит
opaque encrypted blobs, master password никогда не покидает клиент.
Backend полностью реализован (15 endpoints, 1712 LOC + 6 test files),
endpoints `/vault/setup`, `/vault/unlock`, `/vault/secrets/*`, `/vault/groups/*`
принимают base64-encoded byte arrays (auth_hash, ciphertext, wrapped_keys)
без интерпретации.

Frontend **отсутствует полностью**: `frontend/app/vault/` директории нет,
`frontend/lib/api/vault.ts` нет, ни одной crypto-функции на клиенте.
Это блокирует пользователей (staff) от использования vault'а — backend
готов, но запросить даже `POST /vault/setup` через UI невозможно.

ADR-0011 §«Технические следствия» зафиксировал требования: WebCrypto +
Argon2id-через-WASM, secure DOM (no `dangerouslySetInnerHTML`, copy
через Clipboard API c user gesture). Но **не зафиксировал конкретные
библиотеки** для WASM Argon2id, X25519 (Curve25519), HKDF. Без этого
выбора фронтенд начать нельзя — каждая библиотека добавляет npm-зависимость,
требует bundle-size консидерации, и определяет API форму crypto-модуля.

Также ADR-0011 §«Этапы внедрения» упоминал «Stage 1 — Foundation (4-6 PRs)»,
но pure backend. Frontend epic не декомпонован. Без чёткого slicing'а
непонятно, какой PR что закрывает и как остановиться, если scope изменится
mid-flight.

## Решение

### A. Crypto-стек на frontend'е

| Примитив | Источник | Обоснование |
|---|---|---|
| **Argon2id KDF** | `hash-wasm` npm (~25 KB gzipped) | Argon2id не входит в WebCrypto API. `hash-wasm` — чистый WASM без runtime deps, активно maintained (2024+), ~30k weekly downloads. Параметры из ADR-0011 (64 MiB / 3 iter / parallelism 4) поддерживаются. |
| **HKDF-SHA256** | `crypto.subtle.deriveBits` (WebCrypto native) | Стандартная функция, доступна во всех evergreen браузерах. Не требует библиотеки. |
| **AES-256-GCM** | `crypto.subtle.encrypt`/`decrypt` (WebCrypto native) | Hardware-accelerated, constant-time. IV — `crypto.getRandomValues(12 bytes)`. |
| **X25519 keypair + sealed_box** | `@noble/curves` npm (~40 KB gzipped, treeshakeable до ~15 KB для x25519 subset) | Curve25519 не в WebCrypto baseline (Safari имеет, но Firefox добавил только в 2023, baseline ≠ stable). `@noble/curves` — audited (Cure53 2023), pure JS, no WASM, deterministic builds. |
| **CSPRNG** | `crypto.getRandomValues` (WebCrypto native) | Стандартная функция. |
| **Base64 encode/decode** | Native `atob`/`btoa` + `Uint8Array` helpers | Без библиотеки. Helpers в `lib/vault/crypto.ts`. |

**Итого**: +2 npm-зависимости (`hash-wasm`, `@noble/curves`), ~40 KB gzipped к
production bundle'у. Acceptable (vault — staff-only страница, не на
critical path для tenant lending UX).

### B. Module organization

```
frontend/
├── lib/
│   ├── vault/
│   │   ├── crypto.ts          # все WebCrypto + WASM wrappers
│   │   ├── crypto.test.ts     # Vitest unit tests + KAT-векторы
│   │   └── session.ts         # in-memory vault_key store (React-friendly)
│   └── api/
│       ├── vault.ts           # typed API wrappers (mirror backend schemas.py)
│       └── vault.test.ts      # mock fetch
└── app/
    └── vault/
        ├── page.tsx           # router: setup vs unlock vs locked vs unlocked
        ├── _components/
        │   ├── setup-form.tsx       # initial master password setup
        │   ├── unlock-form.tsx      # enter master password to derive key
        │   ├── secrets-list.tsx     # list (encrypted titles → decrypt-on-render)
        │   ├── secret-card.tsx      # single secret view + copy-to-clipboard
        │   ├── create-secret-form.tsx
        │   ├── edit-secret-form.tsx
        │   └── groups-panel.tsx
        └── [secret_id]/
            └── page.tsx
```

### C. Crypto API contract (`lib/vault/crypto.ts`)

Public surface (для UI компонентов):

```ts
// Derivation
deriveKeys(password: string, salt: Uint8Array): Promise<{
  vaultKey: CryptoKey;       // non-extractable AES-GCM key for wrapping
  authHash: Uint8Array;      // 32 bytes, sent to server
}>;

// Per-secret crypto
generateSecretKey(): Promise<CryptoKey>;          // random AES-GCM 256
encryptBlob(secretKey: CryptoKey, plaintext: string): Promise<Uint8Array>; // iv||ct||tag
decryptBlob(secretKey: CryptoKey, blob: Uint8Array): Promise<string>;

// Wrapping (master)
wrapSecretKeyForUser(vaultKey: CryptoKey, secretKey: CryptoKey): Promise<Uint8Array>;
unwrapSecretKeyForUser(vaultKey: CryptoKey, wrapped: Uint8Array): Promise<CryptoKey>;

// Wrapping (group, X25519 sealed_box)
generateX25519Keypair(): { pubkey: Uint8Array; privkey: Uint8Array };
wrapSecretKeyForGroup(groupPubkey: Uint8Array, secretKey: CryptoKey): Promise<Uint8Array>;
unwrapSecretKeyForGroup(privkey: Uint8Array, wrapped: Uint8Array): Promise<CryptoKey>;

// Privkey at-rest (encrypted under vaultKey)
wrapPrivkey(vaultKey: CryptoKey, privkey: Uint8Array): Promise<Uint8Array>;
unwrapPrivkey(vaultKey: CryptoKey, wrapped: Uint8Array): Promise<Uint8Array>;
```

**Инвариант**: `vaultKey` создаётся с `extractable=false` через WebCrypto
`importKey('raw', ..., { name: 'AES-GCM' }, false, ['encrypt','decrypt'])`.
Это означает, что **vaultKey нельзя экспортировать наружу даже изнутри
JS** — defense-in-depth от XSS dump'ов (не bulletproof, но raises bar).
`authHash` — экспортируемый Uint8Array (раз он уходит на сервер).

### D. State management — vault_key в памяти

`vaultKey` живёт **только в `lib/vault/session.ts`** как module-level
mutable variable, обёрнутый через React Context provider для component
доступа. **Никакого persistence**:

- ❌ `localStorage` / `sessionStorage` — XSS exposure, ФЗ-152 risk.
- ❌ IndexedDB — то же.
- ❌ Cookie — leaks к серверу.
- ✅ Module-level memory + `onbeforeunload` zeroize.
- ✅ Auto-lock через `setTimeout(15min)` после unlock'а (тот же TTL что у
  backend `unlock_session_token` per ADR-0011 §«Authentication flow»).

Закрытие вкладки = vault locked. Refresh страницы = vault locked.
Acceptable trade-off: пользователи привыкли заново вводить master password
у Bitwarden/1Password.

### E. Декомпозиция epic'а — 5 slices, 5 PR'ов

**Slice 1 — Crypto foundation + setup flow** (~600 LOC, фокус security):
- ADR-0016 (этот файл).
- `lib/vault/crypto.ts` + `lib/vault/crypto.test.ts` с KAT-векторами для
  каждого примитива (RFC 9106 Argon2id test vectors, RFC 5869 HKDF,
  RFC 7748 X25519 test vectors).
- `lib/vault/session.ts` + tests.
- `lib/api/vault.ts` — `getMe()`, `setup()`, `unlock()` wrappers.
- `app/vault/page.tsx` router-shell + `_components/setup-form.tsx`,
  `_components/unlock-form.tsx`.
- В этом slice **нет secret CRUD UI** — только setup/unlock E2E.
- Acceptance: пользователь может зайти на `/vault`, увидеть «Set up vault»
  prompt, ввести master password, получить `is_setup=true` от сервера,
  на refresh'е увидеть `unlock-form`, ввести password, получить unlock
  success.

**Slice 2 — Personal secrets CRUD** (~500 LOC):
- `_components/secrets-list.tsx` (decrypts titles on-render).
- `_components/create-secret-form.tsx` (encrypts blob client-side, wraps
  с self-wrap only).
- `_components/secret-card.tsx` + `[secret_id]/page.tsx` (decrypt full blob
  on-demand, copy-to-clipboard).
- `_components/edit-secret-form.tsx` (re-encrypt + PUT).
- Delete с confirm.
- Acceptance: end-to-end лично пользоваться vault'ом без групп.

**Slice 3 — Groups + sharing** (~400 LOC):
- `_components/groups-panel.tsx` — list groups, create, manage members.
- Share existing secret с group: re-wrap secret_key под group pubkey.
- Add member to group: re-wrap **всех group's secrets** под нового member'а
  pubkey (linear iteration, acceptable до ~1k secrets/group per ADR-0011).
- Acceptance: команда может расшарить пароль через group, новый member
  видит секреты после добавления.

**Slice 4 — TOTP 2FA** (~250 LOC):
- Encrypt TOTP secret под vaultKey на client'е, отправить на server.
- Verify TOTP local на unlock'е, отправить чек pass/fail на сервер.
- Acceptance: 2FA enforced на unlock после setup'а.

**Slice 5 — Rotation reminders UI** (~200 LOC):
- `expires_at` UI input в create/edit form.
- Список «expiring soon» на главной vault странице.
- Acceptance: пользователь может выставить срок и видит warnings.

**Out of scope (Stage 2 epic)**:
- FIDO2 (hardware token) — ADR-0011 §«Открытые вопросы» 4.
- Emergency access (2-of-2 escrow) — отдельный security ADR.
- Mobile / native клиенты — PWA / native.
- CLI-клиент — Stage 3+.

## Альтернативы

1. **libsodium.js / sodium-plus** — рассматривалось. Преимущества: один
   модуль покрывает Argon2id + sealed_box + AES-GCM. Недостатки: ~200 KB
   WASM bundle (~5x больше hash-wasm + @noble/curves), API менее
   ergonomic для TypeScript, последний release 2022 (less actively
   maintained). Combo hash-wasm + @noble/curves даёт меньше bundle и
   современнее.

2. **WebCrypto-only без Argon2id** (PBKDF2 fallback) — отклонено. PBKDF2
   с iteration count'ом, дающим эквивалентную защиту Argon2id, занимает
   >5 секунд на main thread. UX неприемлемо, и не соответствует ADR-0011
   §«Crypto specification».

3. **Server-side derivation, передача vaultKey клиенту** — отклонено,
   нарушает zero-knowledge (ADR-0011 §«Принципы» 1).

4. **TweetNaCl** (legacy libsodium subset) — отклонено. Pure JS как
   @noble/curves, но менее активно maintained (последний релиз 2022),
   и сам автор @noble автор рекомендует переход на @noble/* family.

5. **`crypto-js`** — отклонено. Известно отсутствие constant-time guarantees,
   небезопасное для production crypto.

## Последствия

### Положительные

- Полная zero-knowledge stack на клиенте, соответствует ADR-0011 и
  ФЗ-152 §§ компании.
- Чёткая декомпозиция epic'а позволяет остановиться после любого slice'а
  с usable vault функциональностью (Slice 1 — нет secret UI, но vault
  setup работает; Slice 2 — личное использование без групп; и т.д.).
- Crypto wrapped в isolated `lib/vault/crypto.ts` — easy для security
  review, KAT vector testing, future migration на FIDO2 / WebAuthn.
- Minimal bundle impact (~40 KB gz) — vault страница code-split автоматически
  через Next.js App Router (`app/vault/*` отдельный chunk).

### Отрицательные / компромиссы

- **Auto-lock 15 min UX** — пользователь будет переввводить master password
  чаще, чем у Bitwarden (15 min default vs auto-fill). Принято per ADR-0011
  trade-off (security > convenience для staff-only tool'а).
- **Argon2id 64 MiB** блокирует main thread ~500 ms на типичном CPU.
  На unlock'е приемлемо, но Web Worker исполнение Argon2id — backlog
  для Slice 1 если перф окажется неприемлемым.
- **No password recovery** — потерянный master password = вечная потеря
  доступа к личным секретам (групповые можно восстановить через
  emergency escrow в Stage 2). UX будет показывать warning при setup'е.
- **Тесты crypto-функций медленные** — Argon2id 64 MiB в Vitest ~500 ms
  per test. Acceptance: marker `@slow` для CI, default suite использует
  reduced parameters (1 iter, 8 MiB) для скорости, отдельный `crypto:full`
  job в CI прогоняет full parameters один раз на PR.

### Технические следствия

- **Новые npm-зависимости**: `hash-wasm@^4.x`, `@noble/curves@^1.x`. Обе —
  pure code, no service calls, no telemetry. Рассмотрены через
  CLAUDE.md §«Запреты»: не сервисы, локальный код только.
- **bundle-analyzer** в CI — добавить assertion на размер vault chunk'а
  (<100 KB gzipped), чтобы deps drift не закрался.
- **`crypto.subtle` требует HTTPS** в production. Dev (localhost) работает.
  Staging/prod — уже на TLS, no impact.
- **Tests**: KAT vectors hardcoded в crypto.test.ts; Argon2id slow tests
  фактически тестируют через hash-wasm (trust upstream), наши тесты
  проверяют integration + параметризацию + correctness HKDF/AES-GCM
  чейнинга.
- **Audit trail**: каждое decrypt'ение секрета → backend audit log
  (`ACTION_VAULT_SECRET_READ`) уже работает. Frontend ничего не пишет
  локально — privacy.
- **Browser compatibility**: ES2022 target (already used в проекте).
  WebCrypto baseline — all evergreen. WASM SIMD не требуется (hash-wasm
  работает и без).

## Открытые вопросы

1. **Web Worker для Argon2id** — Slice 1 решит после prof. Если main
   thread block ~500 ms неприемлем — вынести в Web Worker (добавляет ~50
   LOC + message protocol).
2. **CSP `script-src 'wasm-unsafe-eval'`** — для hash-wasm нужно. Backlog:
   проверить совместимость с текущими CSP headers (next.config.mjs).
3. **Auto-lock UX** — TTL 15 min hardcoded или конфигурируется per-user?
   Per-user — Stage 2 (требует storage user preference; для MVP hardcode).
4. **Clipboard-clear** — после copy секрета, через 30 sec автоматически
   очищать clipboard? UX best practice. Backlog для Slice 2 (низкий
   приоритет, browser API ограничен).

## Этапы внедрения

| PR | Slice | Acceptance |
|---|---|---|
| `#TBD` (этот) | ADR-0016 | merged без code |
| `#TBD` | Slice 1 — crypto + setup/unlock | E2E setup → unlock flow работает |
| `#TBD` | Slice 2 — personal secrets CRUD | Single-user usage end-to-end |
| `#TBD` | Slice 3 — groups + sharing | Team sharing работает |
| `#TBD` | Slice 4 — TOTP 2FA | 2FA enforced |
| `#TBD` | Slice 5 — rotation reminders | UX для expires_at |

После Slice 5 — vault MVP закрыт. Stage 2 (FIDO2, emergency access,
mobile) — отдельные ADR.

## Связанные документы

- ADR-0003 — двухконтурный access_level (HR_RESTRICTED отдельный от
  STAFF_ADMIN).
- ADR-0011 — kb-vault architecture (zero-knowledge, crypto spec, domain
  model).
- ПЗ §8 — Менеджер паролей, доступы, IT-активы.
- Backend: `backend/src/api/vault/` — 15 endpoints, готовые принять
  base64-encoded crypto blobs.
