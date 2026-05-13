# `deploy/secrets/` — SOPS-encrypted secrets

ADR-0009 secrets management. Этот директорий — единственная point of truth
для всех environment secrets.

## Файлы

| Файл | Содержит |
|---|---|
| `dev.enc.yaml` | Local-dev secrets: `POSTGRES_KB_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, `KC_M2M_CLIENT_SECRET`, `LLM_VLLM_API_KEY` (если используется). |
| `staging.enc.yaml` | Staging environment overrides. |
| `prod.enc.yaml` | Production environment overrides. |

**НИКОГДА** не commit'ьте plain-text `.env` / `.env.local` — `.gitignore`
их блокирует, но соблюдайте discipline.

## Использование

### Decrypt для local-dev

```bash
# Один раз: установить sops + age (см. ADR-0009 §"Технические следствия").
brew install sops age   # macOS
# или скачать с github.com/getsops/sops/releases + github.com/FiloSottile/age/releases

# Положить private age key в ~/.config/sops/age/keys.txt (один раз):
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt

# Decrypt → .env.local (gitignored):
make decrypt-dev    # см. infra/Makefile, item 2
```

### Encrypt новые secrets

```bash
# Положить plain-text yaml локально (НЕ commit'ьте):
cat > /tmp/dev.yaml <<EOF
POSTGRES_KB_PASSWORD: super-secret
KC_M2M_CLIENT_SECRET: another-secret
EOF

# Encrypt → deploy/secrets/dev.enc.yaml:
sops encrypt /tmp/dev.yaml > deploy/secrets/dev.enc.yaml
rm /tmp/dev.yaml
```

`.sops.yaml` в repo root объявляет creation rules — recipient public keys
автоматически подбираются по path.

### Edit existing secrets

```bash
# In-place edit через sops (decrypt → $EDITOR → encrypt):
sops deploy/secrets/dev.enc.yaml
```

## Recipients и rotation

См. `.sops.yaml` (repo root) — там живёт mapping path → age recipients.

Rotation:

```bash
# Generate new age key:
age-keygen -o ~/.config/sops/age/keys-2026Q2.txt
# Add public part to .sops.yaml, commit, then rotate all files:
sops rotate -i deploy/secrets/*.enc.yaml
```

ADR-0009 рекомендует **квартальную rotation** + immediate-on-personnel-change.

## DR (disaster recovery)

Потеря **всех** age private keys = полная потеря prod secrets. См.
ADR-0009 §"Открытые вопросы" — backup policy в работе.

Mitigation на старте:
- 2+ recipients для prod (`.sops.yaml` поддерживает `age: key1,key2`).
- Private keys хранятся в 2+ местах (1Password vault Architect'а + physical backup).

## Что НЕ хранить здесь

- **Webhook HMAC secrets** (`webhooks.secret`) — runtime-generated per
  tenant, живут в Postgres. ADR-0009 §"Где НЕ применяется SOPS".
- **JWT'ы / session tokens** — короткоживущие, не persisted.
- **TLS certificates** — manage'ятся cert-manager'ом в k8s, не в git.
