# kb-vault-reminders worker — Kubernetes manifest

Deployment для vault rotation reminder background worker (#167, ADR-0011
§rotation cadence).

## Что в этом директории

| Файл | Назначение |
|---|---|
| `deployment.yaml` | Single-replica Deployment + container spec |

**Нет Service** — worker не listens HTTP; observability через structured
JSON logs в stdout (Loki / ELK pick up via DaemonSet).

## Prerequisites

- Namespace `rehome-kb` (общий с `kb-api` / `kb-indexer`)
- Secret `kb-database` с `DATABASE_URL` (asyncpg DSN)
- Image `ghcr.io/rehome-one/kb-api:<digest>` (тот же main backend; vault
  reminders не нуждаются в HF deps, поэтому Dockerfile.indexer overkill).

## Apply

```bash
sed -i "s|REPLACE_ME_AT_RELEASE|$(docker inspect ghcr.io/rehome-one/kb-api:latest \
  --format='{{index .RepoDigests 0}}' | cut -d@ -f2)|" \
  deploy/k8s/vault_reminders/deployment.yaml

kubectl apply -f deploy/k8s/vault_reminders/
kubectl -n rehome-kb rollout status deployment/kb-vault-reminders
```

## Resource sizing

Minimal — worker idle ~24h, ~1s wake-up для SELECT + log:
- `requests`: 50m CPU / 128Mi memory
- `limits`: 500m / 256Mi (burst headroom)

## Single-replica rationale

Per #167: scan idempotent (downstream notification sink дедуплицирует);
two replica'и удвоили бы log noise без benefit'а. Для horizontal scale:
- Reserve cooperative partition (e.g., `MOD(secret_id_int_hash, REPLICA_COUNT) = REPLICA_INDEX`)
- Or implement `last_reminded_at` field + claim-based locking

Both — backlog (см. #167 description).

## Notification flow

```
kb-vault-reminders pod
  → JSON log line `event=vault.reminder` (stdout)
  → Loki / ELK ingestion
  → Alert routing (Grafana / AlertManager / Slack)
  → Notify secret owner
```

Real email / Telegram delivery — отдельный follow-up (требует SMTP /
bot config + provider ADR).

## Logs example

```json
{
  "ts": "2026-05-14T15:00:00Z",
  "level": "INFO",
  "logger": "src.workers.vault_reminders.runner",
  "event": "vault.reminder",
  "secret_id": "abc-123-...",
  "owner_id": "user-456-...",
  "category": "infra",
  "days_until_expiry": 3,
  "expires_at": "2026-05-17T15:00:00Z"
}
```

## Backlog

- Prometheus metrics (analog #152 для indexer) — reminder_emit_total
  counter
- Real email/Telegram delivery (SMTP / bot config + provider ADR)
- `last_reminded_at` mutation для dedup без downstream sink
- Multi-replica с partition-based claim
