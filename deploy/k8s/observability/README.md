# reHome KB observability — deployable artifacts

Grafana dashboards + alerting templates для production monitoring.
Pin'аются по schema version для reproducibility.

## Файлы

| Файл | Назначение |
|---|---|
| `kb-indexer-dashboard.json` | Grafana dashboard для kb-indexer worker (Cube N, #165) |

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

## Backlog

- **Backend HTTP dashboard** — `http_requests_total` + `http_request_duration_seconds`
  (Cube #108 metrics middleware). Defer until current production
  baselines.
- **Chat / RAG retrieval dashboard** — chat session count, SSE flow
  latency, retrieval hit rate.
- **Vault audit dashboard** — unlock attempts (success/failed),
  secret access patterns (compliance forensic).
- **Service blackbox** — `up` / `probe_success` для liveness rollup.
