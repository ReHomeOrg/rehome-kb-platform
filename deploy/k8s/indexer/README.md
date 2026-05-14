# kb-indexer worker — Kubernetes manifests

Deployment configuration для embedding indexer worker (ADR-0010
§Stage 1, см. также `backend/Dockerfile.indexer`).

## Что в этом директории

| Файл | Назначение |
|---|---|
| `deployment.yaml` | Deployment + container spec (resources, probes, env) |
| `service.yaml` | ClusterIP Service для Prometheus scrape (port 9100) |
| `pvc.yaml` | PVC для HF model cache (5Gi, ReadWriteOnce) |

## Prerequisites

- Namespace `rehome-kb` создан: `kubectl create namespace rehome-kb`
- Secret `kb-database` с `DATABASE_URL` key:
  ```
  kubectl -n rehome-kb create secret generic kb-database \
    --from-literal=DATABASE_URL='postgresql+asyncpg://...'
  ```
- Image `ghcr.io/rehome-one/kb-indexer:<digest>` built из
  `backend/Dockerfile.indexer` и push'нут в registry.
- StorageClass `standard` доступен (или patch'ните `pvc.yaml`).

## Apply

```bash
# Replace image digest в deployment.yaml на актуальный:
sed -i "s|REPLACE_ME_AT_RELEASE|$(docker inspect ghcr.io/rehome-one/kb-indexer:latest \
  --format='{{index .RepoDigests 0}}' | cut -d@ -f2)|" \
  deploy/k8s/indexer/deployment.yaml

kubectl apply -f deploy/k8s/indexer/
kubectl -n rehome-kb rollout status deployment/kb-indexer
```

## Operational notes

### Resource sizing

| Resource | Value | Rationale |
|---|---|---|
| `requests.cpu` | 1 | Mean batch processing — CPU-bound encode |
| `limits.cpu` | 2 | Burst для batch start (Transformer warmup) |
| `requests.memory` | 3Gi | PyTorch 1.5GB + model 2.3GB ≈ 3.8GB; headroom |
| `limits.memory` | 4Gi | OOMKilled если evicted — bump через monitoring |
| PVC storage | 5Gi | Model 2.3GB + tokenizer + альтернативные при blue-green |

### Probes

- **livenessProbe** — `python -c "exit(0)"`. Process-level (PID alive).
  Не проверяет actual indexing — для этого Prometheus alerting
  (`kb_indexer_pending_articles` rate-of-change).
- **readinessProbe** — TCP probe на `:9100` (metrics endpoint).
  Pre-warm 120s — model load ~30s + buffer для cold cache (~5min);
  на second start с cached PVC instantaneous.

### Blue-green re-embedding (ADR-0010 §Stage 1 cutover)

При model bump (e.g., e5-large → e5-large-v2):
1. **Apply** второй Deployment с `EMBEDDING_MODEL` overridden:
   ```
   kubectl apply -f deployment-v2.yaml  # patched name + model
   ```
2. Оба worker'а индексируют параллельно (PK includes
   `embedding_model_id`).
3. Wait до coverage 100% по новой model (Grafana on
   `kb_indexer_pending_articles{model_id="..."}`).
4. **Flip gateway** `EMBEDDING_MODEL` env → restart API pods.
5. После 24-48h burn-in — delete старый Deployment + cleanup vectors:
   ```sql
   DELETE FROM article_embeddings WHERE embedding_model_id = 'OLD';
   ```

### Graceful shutdown

`terminationGracePeriodSeconds: 120` — current batch finish'ит
(typical batch < 30s), потом process exits cleanly. SIGTERM handled
в `runner.py:install_signal_handlers`.

### Prometheus integration

Service `kb-indexer-metrics` exposes /metrics на ClusterIP. Scrape
config (для Prometheus operator ServiceMonitor):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kb-indexer
  namespace: monitoring  # prometheus-operator namespace
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: kb-indexer
  namespaceSelector:
    matchNames:
      - rehome-kb
  endpoints:
    - port: metrics
      interval: 30s
```

Metrics:

- `kb_indexer_articles_processed_total{model_id}`
- `kb_indexer_articles_failed_total{model_id, reason}`
- `kb_indexer_batch_duration_seconds{model_id}` (histogram)
- `kb_indexer_pending_articles{model_id}` (gauge — backlog)

Suggested alerts:

```promql
# Backlog растёт быстрее чем worker processes:
rate(kb_indexer_pending_articles{model_id="..."}[10m]) > 0

# Failure rate > 5%:
rate(kb_indexer_articles_failed_total[5m])
  / rate(kb_indexer_articles_processed_total[5m]) > 0.05

# p95 batch duration > 60s (provider degradation):
histogram_quantile(0.95,
  rate(kb_indexer_batch_duration_seconds_bucket[5m])) > 60
```

## Backlog

- **NetworkPolicy** — restrict /metrics scrape к prometheus pod namespace
- **HPA** на CPU utilization (currently fixed 1 replica)
- **GPU variant** Deployment (для acceleration; CPU-only — startup
  baseline)
- **ServiceMonitor CRD** инклюзив в этот директорий когда стандартизуем
  на prometheus-operator
- **Pre-pulled image hook** через initContainer + emptyDir, чтобы
  избежать ~3.8GB pull на каждом fresh node
