# Runbook: импорт KB v6.7 (prod help.rehome.one)

> Замена статей и документов в `rehome_kb` по `backend/scripts/seed/reHome_KB_master_v6.7.md`.
> Выполнено 2026-06-24. Дельта к v6.5: **+2 статьи** (243 всего), **обновлено 19**, документы (9) — обновлённые редакции оферты/договора.

## Предусловия
- Бэкап БД: `docker exec rehome-postgres pg_dump -U kb -d rehome_kb | gzip > backup_rehome_kb_v67_<ts>.sql.gz`
- Скрипты + transliterate запечены в образе `rehome/kb-platform-indexer:local` (контейнер `rehome-kb-platform-api`).

## Шаги (на сервере 93.77.180.57, внутри контейнера)
Запуск ОБЯЗАТЕЛЬНО через venv-python и `-m` (иначе `ModuleNotFoundError: src`):

```bash
docker cp reHome_KB_master_v6.7.md rehome-kb-platform-api:/tmp/v67.md

# 1. Статьи + категории (upsert по slug; удалений нет — все старые slug присутствуют в v6.7)
docker exec -w /app rehome-kb-platform-api /opt/venv/bin/python \
  -m scripts.import_kb_markdown /tmp/v67.md --direct-db

# 2. Документы: idempotent-by-title скрипт НЕ обновляет содержимое →
#    delete+recreate для обновлённых редакций оферты/договора
docker exec rehome-postgres psql -U kb -d rehome_kb -c "DELETE FROM documents;"
docker exec -w /app rehome-kb-platform-api /opt/venv/bin/python \
  -m scripts.import_kb_documents /tmp/v67.md

# 3. Переиндексация эмбеддингов (provider=hf из env контейнера)
docker exec -w /app rehome-kb-platform-api /opt/venv/bin/python -m scripts.reindex_articles
```

## Контроль
- `SELECT count(*) FROM articles;` → 243 (231 PUBLISHED, 12 DRAFT)
- `SELECT count(*) FROM documents;` → 9
- `SELECT count(*) FROM article_embeddings;` → 231 (= published)
- Старые MinIO-объекты удалённых документов остаются осиротевшими (безвредно, storage-only).
