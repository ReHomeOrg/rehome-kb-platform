# ADR-0022: Vault Stage 2 — FIDO2 / WebAuthn ceremony flow

## Статус

- [x] **Предложено**
- [ ] Принято
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-23
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Требуется approve Архитектора:** scope choice (WebAuthn replacement
  vs supplement TOTP), Authenticator policy, RP identification, attest-
  ation requirements, supplementary keystores (multiple keys per user).

## Контекст

Vault Stage 1 (ADR-0011) использует TOTP в качестве 2nd factor для
unlock'а master password. TOTP fundamentally vulnerable:
- **Phishing** — пользователь может ввести current TOTP code в fake site;
  attacker re-uses 30s окно.
- **Replay** через shared screen / shoulder surf.
- **Seed compromise** — если TOTP secret стащен с client device.

FIDO2 / WebAuthn — public-key challenge-response без shared secret и
phishing-resistant (verifies origin browser → server). Industry-standard
для high-value credentials. Browser native support (Chromium / Firefox /
Safari).

ADR-0011 §«2FA»:
> «Master password + обязательная 2FA (TOTP / FIDO2)»

Stage 1 landed TOTP only (`POST /api/v1/vault/totp/setup` per #146).
Stage 2 adds FIDO2 paths.

Архитектурные ограничения:
1. **ФЗ-152** — все ключевые материалы (public keys, credential IDs,
   sign counters) — в РФ. Internal storage сертификатов не нужен (только
   public key). OK.
2. **Browser-native** — WebAuthn API в browser, без external IdP-сервиса.
3. **Self-hosted library** — Python [py_webauthn](https://github.com/duo-labs/py_webauthn)
   open-source, MIT, no service. OK для CLAUDE.md §6.
4. **No external attestation CA** — accept Self / None attestation
   (TPM / hardware key local attestation only).

## Альтернативы

### Вариант A — FIDO2 заменяет TOTP (recommended)

Stage 2 deprecates TOTP. Existing users мигрируют через "Add FIDO2 key
→ then remove TOTP" UX flow. New users только FIDO2.

**Setup ceremony (registration):**
1. User logged in, opens `/vault/setup-fido2`.
2. Backend `POST /api/v1/vault/fido2/register-begin` returns
   `PublicKeyCredentialCreationOptions` (challenge, rp_id, user_id,
   AuthenticatorSelection criteria).
3. Browser: `navigator.credentials.create({publicKey: options})` →
   authenticator (YubiKey / Touch ID / Windows Hello) prompts user.
4. Browser returns `AttestationResponse` (public key + credentialId).
5. Backend `POST /api/v1/vault/fido2/register-complete` validates +
   stores `vault_fido2_credentials` (id, user_id, credential_id,
   public_key, sign_count, transports, created_at).
6. UI says «FIDO2 key добавлен». Может добавить multiple keys (primary
   + backup) до remove TOTP.

**Unlock ceremony (assertion):**
1. User opens vault, types master password.
2. Backend `POST /api/v1/vault/fido2/assert-begin` returns
   `PublicKeyCredentialRequestOptions` (challenge, allow_credentials
   from user's registered keys).
3. Browser: `navigator.credentials.get({publicKey: options})` →
   authenticator signs challenge.
4. Backend `POST /api/v1/vault/fido2/assert-complete` validates
   signature, increments sign_count.
5. Vault unlocked.

**Pros:**
- Phishing-resistant (origin-bound).
- Hardware-protected private keys (YubiKey / TPM / Secure Enclave).
- Industry standard.
- Native browser support.

**Cons:**
- **Hardware dependency**: пользователи без compatible authenticator
  (старая Win, Linux без libfido2 + biometrics) — blocked. Mitigation:
  Stage 2 keeps TOTP fallback temporarily (см. Вариант C).
- **Key loss = lockout**. Solution: multiple registered keys + emergency
  access (ADR-0021).
- Some authenticators не поддерживают `userVerification=required`
  (RP должен fallback to `preferred`).

### Вариант B — FIDO2 как 3rd factor (additive)

FIDO2 в дополнение к TOTP. Unlock требует master + TOTP + FIDO2.

**Pros:**
- Defense-in-depth.
- Существующие users не теряют access если FIDO2 setup сломается.

**Cons:**
- UX hell — 3 factor unlock каждый раз.
- Дополнительной security не добавляет (TOTP — уже weak link;
  having FIDO2 means TOTP is redundant).

### Вариант C — FIDO2 заменяет TOTP с backward-compat транзитом (predпочительный compromise)

Same как A, но Stage 2 keeps TOTP code-path активным 90 дней.
Migration UX:
- User signs in → видит banner «Migrate to FIDO2 by 2026-08-23».
- Users без FIDO2 by deadline → forced upgrade flow.
- Post-deadline: TOTP endpoint returns 410 Gone.

**Pros:**
- Phasing'd migration; no users locked out.
- Time для buying hardware authenticators corporate.
- Audit data на migration progress.

**Cons:**
- Двойной code-path на 90 days (TOTP + FIDO2).
- Migration deadline нужен enforcer (cron / startup hook).

## Рекомендация

**Вариант C** — phased migration TOTP → FIDO2.

Аргументация:
- Stage 1 TOTP уже landed (#146); cold-cut на FIDO2 потерял бы access
  существующим users без hardware authenticators.
- 90-day deadline = corporate buy-cycle для YubiKeys (~5000₽ × 20 users).
- Post-migration: единственный strong-2FA path (matches industry best
  practice).

## Implementation scope (если C approved)

**Backend:**
1. Migration `0026_vault_fido2`:
   - `vault_fido2_credentials` table (id, user_id FK, credential_id
     unique, public_key bytea, sign_count int, transports text[],
     created_at, last_used_at).
2. Service: `src/api/vault/fido2.py` — WebAuthn ceremony helpers
   (using `py_webauthn` library).
3. Endpoints:
   - `POST /api/v1/vault/fido2/register-begin` (returns challenge).
   - `POST /api/v1/vault/fido2/register-complete` (stores credential).
   - `POST /api/v1/vault/fido2/assert-begin` (returns challenge).
   - `POST /api/v1/vault/fido2/assert-complete` (validates signature,
     issues unlock token).
   - `DELETE /api/v1/vault/fido2/credentials/{id}` (revoke specific key).
   - `GET /api/v1/vault/fido2/credentials` (list user's registered keys).
4. **Settings**:
   - `WEBAUTHN_RP_ID` (e.g. `rehome.one`).
   - `WEBAUTHN_RP_NAME` (e.g. `reHome Vault`).
   - `WEBAUTHN_REQUIRE_USER_VERIFICATION` (default `preferred`).
   - `WEBAUTHN_MIGRATION_DEADLINE` (ISO date; post-deadline TOTP→410).
5. **Migration enforcer** (startup hook): scan vault_users без FIDO2
   credential past deadline → flag for forced upgrade на next login.

**Frontend:**
- `/vault/setup-fido2` — register ceremony (navigator.credentials.create).
- Update `/vault/unlock` — try FIDO2 first, TOTP fallback if
  pre-deadline.
- `/vault/keys` — list + revoke + add additional keys.

**Audit:**
- `vault.fido2.registered` / `vault.fido2.revoked` / `vault.fido2.assert.success`
  / `vault.fido2.assert.failed` action constants.
- Repeated `assert.failed` (>5 за 5 min) → security_incident (brute
  force на FIDO2 не realistic, но possible через replay attempts).

**Tests:**
- Mock authenticator для unit tests (`py_webauthn` provides test
  helpers).
- E2E test через Playwright (virtual authenticator API).

## Открытые вопросы для Архитектора

1. **Approve Вариант C** (phased migration) или A (cold-cut)?
2. **`WEBAUTHN_RP_ID`**: domain registered for rehome.one уже OK?
3. **`AuthenticatorAttachment`**: cross-platform / platform-only /
   either? («platform» = TPM / Touch ID; «cross-platform» = YubiKey).
4. **UserVerification**: `required` / `preferred` / `discouraged`?
5. **Attestation**: `none` / `direct`? (direct требует CA verification —
   overkill для internal app).
6. **Migration deadline**: 90 days? Или другой timeline?
7. **Multiple registered keys per user**: max 5? Или unlimited?
8. **Backup procedure**: если user roams между devices — Passkey
   (sync'd через iCloud / Google) или strict hardware-only?

## Implementation gating

PR с реализацией создаётся ТОЛЬКО ПОСЛЕ ADR approve. Без approve'а
рассматривается как design-violation per CLAUDE.md §9.
