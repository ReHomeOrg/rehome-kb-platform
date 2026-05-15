# reHome KB observability — deployable artifacts

Grafana dashboards + alerting templates для production monitoring.
Pin'аются по schema version для reproducibility.

## Файлы

| Файл | Назначение |
|---|---|
| `kb-api-dashboard.json` | Grafana dashboard для kb-api gateway (Cube AA, #178) |
| `kb-chat-rag-dashboard.json` | Grafana dashboard для chat + RAG retrieval (Cube BB, #179) |
| `kb-indexer-dashboard.json` | Grafana dashboard для kb-indexer worker (Cube N, #165) |
| `kb-services-up-dashboard.json` | Grafana dashboard для liveness rollup (Cube EE, #182) |
| `kb-webhooks-dashboard.json` | Grafana dashboard для webhook delivery worker (Cube X, #175) |
| `kb-vault-reminders-dashboard.json` | Grafana dashboard для vault rotation reminders (Cube Z, #177) |
| `kb-vault-audit-dashboard.json` | Grafana dashboard для vault security/audit (Cube CC, #180) |

## kb-indexer dashboard

**Назначение**: monitoring embedding worker'а (ADR-0010 Stage 1).
Combines metrics из `workers/indexer/metrics.py` (Cube A, #152).

### Panels

1. **Pending articles (backlog)** — `kb_indexer_pending_articles` gauge
   stat. Thresholds: green <100 / yellow 100-500 / red >500.
   - Fluctuating gauge normal (new articles → spike → drain)
   - Persistent growth = worker can't keep up; scale up или batch_size++

2. **Processed rate (5m)** — `rate(kb_indexer_articles_processed_total)`.
   Drain rate; baseline зависит от batch_size + poll_interval +
   provider latency.

3. **Failed rate (5m, by reason)** — `rate(kb_indexer_articles_failed_total)`.
   Sustained non-zero = provider/DB outage → check logs.

4. **Failure ratio (5m)** — `failed / (failed + processed)`.
   Thresholds: green <1% / yellow 1-5% / red >5%.
   Sparse 100% spikes допустимы (transient errors).

5. **Batch duration (p50/p95/p99, 5m)** — histogram quantiles.
   Typical 1-10s; p95 >60s = provider degradation или batch too large.

### Import

```bash
# Grafana UI → Dashboards → Import → Upload JSON file:
deploy/k8s/observability/kb-indexer-dashboard.json

# Or via provisioning (recommended для k8s deploy'а):
kubectl create configmap kb-indexer-dashboard \
  -n monitoring \
  --from-file=deploy/k8s/observability/kb-indexer-dashboard.json
# затем mount в Grafana sidecar / native provisioning path.
```

Template variable `DS_PROMETHEUS` — выбирается из доступных Prometheus
datasource'ов; default «Prometheus».

### Suggested alerts (AlertManager rules)

Не часть dashboard JSON'а — отдельная provisioning. Suggested PromQL:

```yaml
groups:
  - name: kb-indexer
    interval: 30s
    rules:
      - alert: KbIndexerBacklogGrowing
        expr: rate(kb_indexer_pending_articles[10m]) > 0
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "kb-indexer backlog растёт {{$value}}/s за последние 30 мин"
          description: "Backlog накапливается — worker не успевает или провайдер замедлился"

      - alert: KbIndexerHighFailureRate
        expr: |
          sum(rate(kb_indexer_articles_failed_total[5m]))
            / sum(rate(kb_indexer_articles_processed_total[5m] OR vector(0)))
              > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "kb-indexer failure rate >5% за 5 минут"
          description: "Проверь logs: kubectl logs -n rehome-kb deploy/kb-indexer"

      - alert: KbIndexerBatchSlow
        expr: |
          histogram_quantile(0.95,
            sum by (model_id, le)
              (rate(kb_indexer_batch_duration_seconds_bucket[5m]))) > 60
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "kb-indexer p95 batch duration >60s"
          description: "HF provider degradation или batch_size too large"
```

## kb-webhooks dashboard

**Назначение**: monitoring webhook delivery worker'а (E5.2). Combines
metrics из `src/api/webhooks/metrics.py` (Cube W, #174).

### Panels

1. **Delivered rate (last)** — `rate(kb_webhook_deliveries_total{status="delivered"})`
   stat. Baseline зависит от event volume; внезапный 0 при non-zero
   retries → endpoint down.

2. **Delivery rate by status (5m)** — `rate(kb_webhook_deliveries_total)`
   broken by `status` label. Visualization: discriminate `delivered`
   от `failed_4xx`/`failed_5xx`/`failed_network`.

3. **Failure ratio (5m)** — `(failed_*) / (all)`. Thresholds:
   green <1% / yellow 1-5% / red >5%. Spikes 100% при transient
   subscriber outage норма.

4. **Retries by event_type (5m)** — `rate(kb_webhook_retries_total)`.
   Per-event_type breakdown показывает, какой downstream деградирует.

5. **Delivery duration (p50/p95/p99, 5m, by event_type)** —
   histogram quantiles. Baseline 50-200ms (LAN subscriber); p95 >5s
   = subscriber slow или TLS handshake issue.

## kb-vault-reminders dashboard

**Назначение**: monitoring daily scanner за expiring vault secrets
(ADR-0011 zero-knowledge). Metrics из `src/workers/vault_reminders/metrics.py`
(Cube Y, #176).

### Panels

1. **Scans (last 24h)** — `increase(kb_vault_reminders_scan_total[24h])`.
   Expected ≥1; 0 → cron died. Thresholds red <1 / green ≥1.

2. **Scan errors (last 24h)** — `increase(kb_vault_reminders_scan_errors_total[24h])`.
   ≥1 → investigate logs. Thresholds green=0 / red ≥1.

3. **Reminders emitted (7d, by category)** — bar chart по
   `vault_secrets.category`. Persistent skew → review rotation policy.

4. **Cumulative scans + reminders** — smooth slope = healthy daily cron;
   plateau = worker died.

5. **Scan duration (p50/p95/p99, 1h)** — histogram quantiles. Baseline
   50-200ms; p95 >1s → DB load или vault scale ballooning.

### Suggested alerts

```yaml
groups:
  - name: kb-webhooks
    interval: 30s
    rules:
      - alert: KbWebhooksHighFailureRate
        expr: |
          sum(rate(kb_webhook_deliveries_total{status!="delivered"}[5m]))
            / sum(rate(kb_webhook_deliveries_total[5m]))
              > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "kb-webhooks failure rate >5% за 10 минут"
          description: "Check subscriber endpoints, network egress, DNS"

      - alert: KbWebhooksSlowDelivery
        expr: |
          histogram_quantile(0.95,
            sum by (event_type, le)
              (rate(kb_webhook_delivery_duration_seconds_bucket[5m]))) > 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "kb-webhooks p95 delivery >5s для {{$labels.event_type}}"

  - name: kb-vault-reminders
    interval: 30s
    rules:
      - alert: KbVaultRemindersScanMissed
        expr: increase(kb_vault_reminders_scan_total[26h]) < 1
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "kb-vault-reminders: nothing scanned за >24h"
          description: "Worker died или scan_interval misconfig"

      - alert: KbVaultRemindersErrors
        expr: increase(kb_vault_reminders_scan_errors_total[24h]) > 0
        for: 0m
        labels:
          severity: warning
        annotations:
          summary: "kb-vault-reminders scan failure(s)"
          description: "Check: kubectl logs -n rehome-kb deploy/kb-vault-reminders"
```

## kb-api dashboard

**Назначение**: monitoring API gateway HTTP-traffic. Metrics из
`src/api/observability/metrics.py` (Cube #108 middleware).

### Panels

1. **Total RPS (5m)** — `sum(rate(http_requests_total))` stat.
2. **5xx ratio (5m)** — `5xx / total` stat. Thresholds green <0.1%
   / yellow 0.1-1% / red >1%.
3. **Request rate by status class (5m)** — stacked timeseries по
   1xx/2xx/3xx/4xx/5xx (label_replace status → status_class).
4. **Request latency p50/p95/p99 (5m, all routes)** — histogram
   quantiles aggregated.
5. **Top 10 slowest routes (p95, 5m)** — `topk(10, ...)` highlights,
   что нужно optimize first.
6. **Top 10 routes by RPS (5m)** — capacity planning + hot paths.

## kb-chat-rag dashboard

**Назначение**: monitoring chat traffic + RAG retrieval health.
Metrics из `src/api/chat/metrics.py` + `src/api/search/metrics.py`
(Cube BB, #179).

### Panels

1. **Sessions created (1h, by scope)** — stacked bars по guest/tenant/
   staff/legal. Traffic distribution.
2. **Messages sent rate (5m, by scope)** — counter rate.
3. **Retrieval hit ratio (5m)** — `has_results=yes / total`. Thresholds
   red <30% / yellow 30-60% / green ≥60%. Low ratio → корпус мал или
   embedding model drift.
4. **Retrieval duration p50/p95/p99 (5m)** — histogram quantiles.
   Baseline ~100ms; p95 >500ms → HF provider / DB load.
5. **Chat message E2E duration (5m, JSON + SSE)** — retrieval + LLM.
   Outliers до 30s. SSE observed в generator `finally` (#181).

## kb-vault-audit dashboard

**Назначение**: security forensic — vault unlock attempts + secret
access patterns. Metrics из `src/api/vault/metrics.py` (Cube CC, #180).

Zero-knowledge invariant (ADR-0011): metrics не leak'ят PII. Labels —
только `result`, `action`, `category` (fixed enum). Никаких user_id /
secret_id / plaintext.

### Panels

1. **Failed unlock attempts (last 1h)** — stat. Thresholds green=0 /
   yellow ≥5 / red ≥20 (bruteforce indicator).
2. **Unlock success ratio (15m)** — stat. Sustained <50% → UX bug
   or attack. Thresholds red <50% / yellow / green ≥90%.
3. **Unlock rate by result (5m)** — timeseries discriminates
   success / failed lines.
4. **Secret access rate by action (5m)** — stacked created/read/deleted.
5. **Secret reads by category (1h)** — bar chart skew detection
   (hot keys vs cold certs).
6. **Cumulative vault events** — slope-based liveness check.

### Suggested alerts

```yaml
groups:
  - name: kb-api
    interval: 30s
    rules:
      - alert: KbApiHigh5xxRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
            / sum(rate(http_requests_total[5m]))
              > 0.01
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "kb-api 5xx ratio >1% за 5 минут"
          description: "Backend regression — check logs immediately"

      - alert: KbApiSlowResponses
        expr: |
          histogram_quantile(0.95,
            sum by (route, le)
              (rate(http_request_duration_seconds_bucket[5m]))) > 2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "kb-api p95 latency >2s для {{$labels.route}}"

  - name: kb-chat-rag
    interval: 30s
    rules:
      - alert: KbRetrievalLowHitRatio
        expr: |
          sum(rate(kb_retrieval_total{has_results="yes"}[15m]))
            / sum(rate(kb_retrieval_total[15m]))
              < 0.3
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "kb-retrieval hit ratio <30% за 30 минут"
          description: "Корпус не покрывает запросы / embedding drift"

      - alert: KbRetrievalSlow
        expr: |
          histogram_quantile(0.95,
            sum by (le)
              (rate(kb_retrieval_duration_seconds_bucket[5m]))) > 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "kb-retrieval p95 >500ms"

  - name: kb-vault-audit
    interval: 30s
    rules:
      - alert: KbVaultBruteforceSuspected
        expr: increase(kb_vault_unlock_total{result="failed"}[1h]) > 50
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: ">50 failed unlocks за час — возможный bruteforce"
          description: "Cross-reference с audit_log по user_id для identification"

      - alert: KbVaultUnlockFailureSpike
        expr: |
          sum(rate(kb_vault_unlock_total{result="failed"}[5m]))
            / sum(rate(kb_vault_unlock_total[5m]))
              > 0.5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "kb-vault unlock failure rate >50% за 10 минут"
          description: "Либо bruteforce, либо backend хеш-validator broken"
```

## kb-services-up dashboard

**Назначение**: liveness rollup всех scrape targets `rehome-kb`
namespace. Использует built-in Prometheus метрики (`up`,
`scrape_duration_seconds`) — no app-level instrumentation нужно.
Job filter — `job=~"kb-.*"`.

### Panels

1. **Service status (live)** — `up` value mapping 0→DOWN / 1→UP.
   Big horizontal stat для at-a-glance overview.
2. **Service up/down over time** — timeline по каждому target'у
   (fillOpacity 30%). Discriminates flapping от sustained outage.
3. **Uptime ratio (24h SLO)** — `avg_over_time(up[24h])`. Thresholds
   red <99% / yellow 99-99.9% / green ≥99.9%.
4. **Scrape duration per target** — `scrape_duration_seconds`.
   Sustained >1s → target slow / overloaded.

### Suggested alerts

```yaml
groups:
  - name: kb-services-up
    interval: 30s
    rules:
      - alert: KbServiceDown
        expr: up{job=~"kb-.*"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "kb service {{$labels.job}} ({{$labels.instance}}) DOWN"
          description: "Prometheus scrape failed за >2 минут"

      - alert: KbServiceSloBurn
        expr: avg_over_time(up{job=~"kb-.*"}[1h]) < 0.99
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "kb service {{$labels.job}} uptime <99% за час"
```

## Backlog

_(empty — Stage 1 observability coverage complete.)_
