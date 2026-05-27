# Backend ad-hoc scripts

Скрипты для разовых ops/dev задач — НЕ часть production runtime.

## `import_kb_articles.py`

Парсит .docx документы (FAQ + KB) и POST'ит статьи через
`/api/v1/articles`. Использует m2m JWT.

```bash
# 1. Получить токен:
TOKEN=$(curl -s -X POST http://localhost:8080/realms/rehome/protocol/openid-connect/token \
  -d "client_id=rehome-platform-m2m" \
  -d "client_secret=rehome-platform-m2m-local-dev-secret" \
  -d "grant_type=client_credentials" | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
echo "$TOKEN" > /tmp/.kb-token

# 2. Запустить импорт:
.venv/bin/python scripts/import_kb_articles.py
```

FAQ статьи получают тег `topfaq` — landing page `/` query'ит их для
блока «Популярные вопросы».

## `reindex_articles.py`

Bypass-скрипт для `IndexerService.reindex_all_articles` — обходит
admin_task transaction race (open bug — `/api/v1/admin/reindex` сейчас
не работает корректно из-за timing'а commit'а). Использует
MockEmbeddingProvider (deterministic SHA — для dev/demo достаточно).

```bash
.venv/bin/python scripts/reindex_articles.py
# Output: OK: articles_processed=N, chunks=N, errors=0
```

После reindex embeddings persist'ятся в `article_embeddings` (pgvector).
Чтобы `/api/v1/search` действительно использовал их — backend должен
быть запущен с `RAG_ENABLED=true`.

**Known issue**: pgvector ↔ SQLAlchemy deserialization падает на
read path (см. `pgvector/vector.py:from_text` — `'float' object is not
subscriptable`). Это lib-version mismatch, отдельный bug к фиксу.
