# ADR-0017: Vault group sharing — multi-user wraps вместо group keypair

## Статус

[ ] Предложено
[x] Принято
[ ] Заменено ADR-MMMM
[ ] Отклонено

- **Дата:** 2026-05-17
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** да, 2026-05-17 (чат-сессия, kickoff sharing-gap close)
- **Дополняет:** ADR-0011 (Vault architecture), ADR-0016 (Vault frontend)

## Контекст

ADR-0011 §«Crypto specification» / «Group keypair» утвердил **X25519 keypair
на каждую группу** для асимметричного sharing: per-secret key обёрнут
публичным ключом группы (`sealed_box`-style), любой member знает privkey
группы и может unwrap'нуть.

**Реальность реализации (Slice 1 + Slice 2 + Slice 3 narrowed):**

- `vault_groups` table **не имеет** keypair-колонок (см.
  `backend/src/api/vault/models.py:58-77`). Migration `0016_vault_foundation`
  и `0017_vault_groups` не landed group keypair поля.
- `vault_secret_wraps` имеет `(user_id, group_id, wrapped_key)` с CHECK
  `XOR(user_id, group_id)` — но group_id wraps нельзя decrypt'ить никаким
  realистичным способом, потому что нет group privkey.
- `can_user_access_secret` (repository) check'ит и user wraps, и group wraps
  — но эта authorization broken: даже если user — group member, у него
  нет privkey'а, чтобы decrypt wrapped_key, который lay'нут под несуществующим
  group pubkey.

Slice 3 (PR #251) высветил gap: backend groups management работает, но
**нет ни одного способа реально расшарить секрет с группой**. Этот ADR
закрывает gap, заменяя архитектурное решение ADR-0011 §«Group keypair»
на более прагматичное.

## Решение

### A. Отказ от group keypair

`vault_groups` остаётся без keypair колонок. Concept «group has X25519
keypair» удаляется из crypto model. ADR-0011 §«Group keypair» считается
**superseded by this ADR**.

Группа становится **organizational primitive** (membership tracking +
role management), не crypto primitive.

### B. Multi-user wraps

Sharing секрета с группой == создание **множества user_id wraps**, по
одному на каждого текущего члена группы. Каждый wrap зашифрован под
user.x25519_pubkey того конкретного user'а.

```
vault_secret_wraps row (после ADR-0017):
  secret_id   (FK)
  user_id     (NOT NULL) — recipient
  group_id    (NULL OR FK) — lineage: кто шарингом породил wrap (для audit
                            + re-share-on-add-member trace)
  wrapped_key (encrypted под user_id's pubkey)
```

**Schema migration**:
1. Drop `ck_vault_secret_wraps_xor` CHECK.
2. `user_id` становится NOT NULL.
3. `group_id` остаётся NULLABLE (теперь — pure metadata).
4. Backfill: existing group-only wraps (если таковые есть в production
   — currently NONE, Stage 1 не production) удаляются. На dev/test —
   migration ставит NOT NULL после `DELETE WHERE user_id IS NULL`.

**Updated PRIMARY KEY**: `(secret_id, user_id, COALESCE(group_id, '...'))`
— allows тот же user-recipient через несколько групп (rare edge case;
если pragmatic — оставляем PK `(secret_id, user_id)`, теряя multi-share-via-different-groups
information). **Decision**: оставляем PK `(secret_id, user_id)`, group_id
— "first wrap lineage" tracking only.

### C. Новые endpoints

```
GET /api/v1/vault/users/{user_id}/pubkey
  → 200 { user_id, x25519_pubkey_b64 }
  → 404 если user не setup'нул vault
  Auth: any authenticated user (vault_users.x25519_pubkey — public по
        design ADR-0011). 401 anon.

POST /api/v1/vault/secrets/{secret_id}/wraps
  body: { wraps: [{user_id, group_id?, wrapped_key_b64}] }
  → 201 / 204 (no content) — added wraps
  → 403 если caller не имеет access к secret'у (anti-leak)
  → 409 если user уже в wraps этого secret'а (idempotent — return existing)
  Auth: any user с access к secret'у (verify через can_user_access_secret).

DELETE /api/v1/vault/secrets/{secret_id}/wraps/{user_id}
  → 204
  → 403 если caller — не owner (только owner может unshare)
  → 404 если wrap не существует.
  Auth: owner-only.
```

`POST /vault/secrets/{secret_id}/wraps` ловит case'ы:
- Share с группой: client iterates current members of group, POSTs wraps
  per-member.
- Add member to group → re-wrap each group's secrets для new member.
- Manual share с individual user.

### D. Lineage tracking

`group_id` колонка остаётся как **read-only audit metadata**:

- При share-with-group: client заполняет `group_id` field в каждом
  wrap'е → backend сохраняет.
- На list members / list group's shared secrets — query `WHERE group_id = G`.
- При remove member из группы: backend (или frontend) удаляет wraps
  где `user_id = removed_user AND group_id = G`. Other group_id'ы для
  того же user'а остаются.

Эта lineage **не используется для authorization** — только для UX
("какие секреты были расшарены с этой группой", "при add member —
какие secrets re-share").

### E. Frontend flow (Slice 3.5)

**Share with group** (на secret detail page):
1. Owner кликает «Поделиться» → выбирает группу.
2. Client fetches GET `/vault/groups/{G}/members` → список user_ids.
3. Для каждого member:
   - GET `/vault/users/{user_id}/pubkey`.
   - Decrypt own wrap → recover secret_key.
   - Wrap secret_key под user.pubkey через `wrapSecretKeyForGroup`
     (X25519 sealed-box; реализовано в Slice 1 crypto.ts).
4. POST `/vault/secrets/{secret_id}/wraps` с batch wraps (group_id=G в
   каждом).

**Add member with re-share** (на group members panel):
1. Owner добавляет member: POST `/vault/groups/{G}/members`.
2. UI prompt: «Re-share existing group secrets to new member?»
3. Если yes: client fetches secrets где `group_id=G` lineage (через
   список секретов owner'а — filter client-side by checking wraps;
   OR через новый endpoint `GET /vault/groups/{G}/secrets` — backlog).
4. Для каждого: re-wrap + POST wraps.

**Remove member** (на group members panel):
1. Owner удаляет member: DELETE `/vault/groups/{G}/members/{user_id}`.
2. UI prompt: «Revoke access removed member's wraps?»
3. Если yes: client iterates secrets с lineage `group_id=G` где
   `user_id=removed_user_id` → DELETE `/vault/secrets/{S}/wraps/{user_id}`.

NB: revoke (remove wrap) **не делает старые secret_keys forgotten** —
removed member мог cache'ить secret_key из cleartext browser memory. Это
acceptable per Stage 1 ADR-0011 §«Открытые вопросы». Истинный revoke —
rotate secret_key (re-encrypt blob + re-wrap для всех current
recipients) — backlog Stage 2.

## Альтернативы

1. **True group keypair** (как изначально планировал ADR-0011):
   - Plus: одна wrap на группу — фиксированная стоимость sharing.
   - Minus: где хранится group privkey? Должна быть accessible всем
     members группы. Это значит — на каждом add/remove member нужен
     **полный re-wrap всех secrets** под новый "group session keypair".
     Получается та же linear работа что и multi-user wraps, но с лишним
     уровнем абстракции.
   - Minus: storage и distribution group privkey complicated. Wrap его
     под user_keys → де facto multi-user wrap. Без user-keys → не
     zero-knowledge (нужен ещё один escrow service).
   - **Отклонено**: linear cost в обоих случаях, multi-user wraps проще
     model'но и операционно.

2. **Encryption-by-default к owner only + sharing as ACL** (server-side
   key escrow):
   - Plus: один wrap всегда.
   - Minus: нарушает zero-knowledge (server holds key). ADR-0011
     §«Принципы» 1.
   - **Отклонено**.

3. **Keep schema as-is, just не используем group_id wraps**:
   - Plus: zero migration.
   - Minus: dead-code data (CHECK constraint still allows group_id-only
     wraps, которые ни в один code path не decryptable). Drift между
     schema и reality. Confusing для future contributors.
   - **Отклонено**.

4. **Lineage в отдельной таблице** `vault_secret_shares(secret_id, group_id)`:
   - Plus: cleaner separation of concerns.
   - Minus: extra JOIN на каждой share-related операции, дополнительная
     migration. Group_id колонка в wraps уже есть — дешевле использовать.
   - **Отклонено** в пользу in-table column.

## Последствия

### Положительные

- Sharing реально работает end-to-end (closes ADR-0011 §Group sharing
  semantic gap).
- Stays zero-knowledge: каждый wrap по-прежнему под user-specific pubkey;
  server не decrypt'ит.
- Audit lineage преcservved через `group_id` колонку — full history
  кто шеринил с какой группой.
- Существующая `wrapSecretKeyForGroup` функция в Slice 1's `crypto.ts`
  переиспользуется без изменений (она именно так и работала — X25519
  sealed-box per user pubkey).

### Отрицательные / компромиссы

- **Linear cost при add/remove member**: O(N_secrets_in_group) crypto
  operations. Acceptable до ~1k secrets/group per ADR-0011 §«Group
  membership change». При scaling — backend epic для bulk re-wrap +
  pubkey-batch endpoint.
- **Revoke не forgets**: removed member's browser memory мог cache'ить
  unwrapped secret_key. True forget = rotate. Backlog Stage 2.
- **Lineage через single FK column** — если same user appended к
  secret через две группы, lineage показывает только одну (первую).
  Edge case; acceptable trade-off.

### Технические следствия

- **Migration** `0018_vault_wraps_multi_user.py`:
  - DELETE wraps WHERE user_id IS NULL (только если в DB существуют —
    в test/dev может быть, в production currently нет live data).
  - ALTER COLUMN user_id SET NOT NULL.
  - DROP CONSTRAINT ck_vault_secret_wraps_xor.
- **Endpoints**: 2 new (`GET /vault/users/{id}/pubkey`,
  `POST /vault/secrets/{id}/wraps`) + 1 (`DELETE /vault/secrets/{id}/wraps/{user_id}`).
- **Repository**: новые методы `get_user_pubkey`, `add_secret_wraps`,
  `remove_secret_wrap`.
- **Audit**: actions `vault.secret.shared` (POST wraps), `vault.secret.unshared`
  (DELETE wrap). Resource = vault_secret, metadata = `{added_users, group_id}` /
  `{removed_user, group_id}`.
- **Frontend**: новый component для secret-detail "Share..." panel +
  group-members add-with-share dialog.

## Открытые вопросы

1. **Bulk endpoint для pubkey lookup** — N member группы → N HTTP calls
   на каждый pubkey. Acceptable для small groups (<50), для bigger —
   backlog `POST /vault/users/pubkeys [user_ids...]` batch endpoint.
2. **List group's shared secrets endpoint** — `GET /vault/groups/{G}/secrets`
   для UI «секреты, расшаренные с этой группой». Backlog (можно derive
   client-side из существующего list + per-secret wrap check, но
   неэффективно).
3. ~~**Rotate secret_key** (true revoke) — Stage 2.~~ **DONE 2026-05-27**:
   `POST /vault/secrets/{secret_id}/rotate` (backend). Owner-only;
   atomic replace blob + wraps в single transaction (SELECT FOR UPDATE
   на blob + DELETE all wraps + INSERT new wraps + UPDATE blob.ciphertext
   + bump payload_version). Прерывает «cached plaintext» exposure у
   revoked recipients. Frontend rotation UI — отдельный slice (нетривиальная
   client-side crypto: decrypt → regenerate → re-encrypt → re-wrap для
   surviving users). См. `VaultRepository.rotate_secret_atomic` + audit
   action `vault.secret.rotated`.
4. **Concurrent share races** — два owner'а одновременно расшаривают
   тот же secret с разными группами; backend нужен UQ `(secret_id, user_id)`
   PK уже это даёт. Race на DELETE одного / POST другого — last-write-wins,
   ok.

## Этапы внедрения

| PR | Содержимое | Acceptance |
|---|---|---|
| `#TBD` (этот) | ADR-0017 | merged |
| `#TBD` | Backend: migration + 3 endpoints + repository methods + unit tests | All tests pass; cURL flows работают |
| `#TBD` | Frontend Slice 3.5: share-with-group UI + add-member-with-reshare | End-to-end sharing работает |

## Связанные документы

- ADR-0011 — Vault architecture (this ADR supersedes §«Group keypair»
  и §«Group sharing — асимметричное»).
- ADR-0016 — Vault frontend (§E Slice 3 amended).
- ПЗ §8.3 — групповой доступ к секретам.
