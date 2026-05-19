# Observability — Prometheus / Alerts (#241)

Сводка по метрикам, alert'ам и wire-up'у для production deployment.

## Метрики, экспортируемые backend'ом

Все экспортируются через единый `/metrics` endpoint основного FastAPI
приложения (см. `src/api/observability/metrics.py` middleware + per-module
`metrics.py`). Cardinality каждой метрики ограничена fixed enum labels
(нет неограниченных labels вроде user_id / IP).

### HTTP / Gateway (`src/api/observability/metrics.py`)
- `http_requests_total{method, route, status}` — Counter.
- `http_request_duration_seconds{method, route}` — Histogram.

### Webhooks (`src/api/webhooks/metrics.py`)
- `kb_webhook_deliveries_total{event_type, status}` — Counter (status ∈
  `delivered` / `failed_network` / `failed_4xx` / `failed_5xx`).
- `kb_webhook_delivery_duration_seconds{event_type}` — Histogram.
- `kb_webhook_retries_total{event_type}` — Counter.

### Chat (`src/api/chat/metrics.py`)
- `kb_chat_sessions_created_total{scope}` — Counter.
- `kb_chat_messages_total{scope}` — Counter.
- `kb_chat_message_duration_seconds{scope}` — Histogram.

### Vault (`src/api/vault/metrics.py`)
- `kb_vault_unlock_total{result}` — Counter (result ∈ `success`/`failed`).
- `kb_vault_secret_access_total{action, category}` — Counter (action ∈
  `read`/`create`/`update`/`delete`/`share`).

### Search / RAG (`src/api/search/metrics.py`)
- `kb_retrieval_total{has_results}` — Counter.
- `kb_retrieval_duration_seconds` — Histogram.
- `kb_retrieval_hits` — Histogram (hits count distribution).
- `kb_rerank_total{provider}` — Counter.
- `kb_rerank_duration_seconds{provider}` — Histogram.
- `kb_rerank_hits{provider}` — Histogram.

### Documents (`src/api/documents/metrics.py`)
- `kb_documents_files_downloaded_total` — Counter (no status label —
  см. backlog в alert_rules.yml).
- `kb_documents_files_uploaded_total` — Counter.

### Workers (`src/workers/*/metrics.py`)
- **popular_query**: `kb_popular_query_scan_total{result}`,
  `..._scan_errors_total`, `..._dispatch_total`, `..._queries_emitted`
  (Histogram), `..._scan_duration_seconds`.
- **vault_reminders**: `kb_vault_reminders_scan_total{result}`,
  `..._emitted_total`, `..._scan_duration_seconds`,
  `..._scan_errors_total`.
- **indexer**: `kb_indexer_articles_processed_total`,
  `..._articles_failed_total`, `..._batch_duration_seconds`,
  `..._pending_articles` (Gauge).

## Alert rules

Файл: [`ops/observability/prometheus/alert_rules.yml`](../ops/observability/prometheus/alert_rules.yml).

Severity convention:
- `critical` — production user impact (chat broken, vault locked,
  HTTP 5xx spike, brute-force pattern).
- `warning` — degradation / suspicious pattern (high failure rate,
  slow latency, unusual access volume).
- `info` — operational signal (content gaps, low activity).

Группы alerts:
- `http` — HTTP error rate / latency.
- `webhooks` — delivery failure rate, retry storms.
- `vault` — failed-unlock spike (ФЗ-152 §17.1 brute-force signal),
  unusual secret access volume.
- `chat` — LLM latency degradation.
- `search` — retrieval latency, no-results rate (content gap).
- `workers` — popular_query / vault_reminders / indexer health.
- `documents` — placeholder (нужен status label на upload metric).

## Production wiring

### Prometheus

`prometheus.yml`:
```yaml
scrape_configs:
  - job_name: rehome-kb
    static_configs:
      - targets: ['kb-api:8000']
    metrics_path: /metrics
rule_files:
  - /etc/prometheus/rules/alert_rules.yml
```

Скопировать `ops/observability/prometheus/alert_rules.yml` в
`/etc/prometheus/rules/` при deploy'е.

### Alertmanager

Route'ы по severity:
- `critical` → pager (PagerDuty / Opsgenie).
- `warning` → ops Slack channel.
- `info` → daily digest.

### Grafana

Dashboards — backlog (см. CS.11 в state-of-code.md). Минимальный
viable набор queries для quick dashboards:
- `sum(rate(kb_webhook_deliveries_total{status="delivered"}[5m])) by (event_type)`
- `histogram_quantile(0.95, sum by (le, scope) (rate(kb_chat_message_duration_seconds_bucket[5m])))`
- `sum(rate(kb_vault_unlock_total[1h])) by (result)`
- `histogram_quantile(0.95, sum by (le) (rate(kb_retrieval_duration_seconds_bucket[5m])))`

## Cardinality budget

Все метрики имеют bounded label sets — нет risk кардинальности взрыва:
- Worst case: `kb_webhook_deliveries_total` = ~17 event_types × 4 statuses
  = 68 series.
- `http_*` = 30 routes × 7 methods × ~5 statuses ≈ 1000 series.
- Vault `kb_vault_secret_access_total` = 5 actions × ~10 categories
  = 50 series.

Total <2000 series — Prometheus single-instance capacity OK.
