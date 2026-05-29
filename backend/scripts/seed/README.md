# KB seed source-of-truth

Per ADR-0027: оригинальные .docx статей хранятся в MinIO bucket `kb-seed`,
не в Git LFS, не в архитекторской машине. Это reproducibility-источник
для `import_kb_articles.py` (см. соседний модуль).

## Bucket layout

    s3://kb-seed/articles/<VERSION>/<filename>.docx

Где `<VERSION>` — дата выгрузки seed-набора (`YYYY-MM-DD`), pinned в
`import_kb_articles.py::SEED_VERSION`.

## Текущая версия

`SEED_VERSION = "2026-05-28"` — see `backend/scripts/import_kb_articles.py`.

| File                              | sha256                                                             |
| --------------------------------- | ------------------------------------------------------------------ |
| `reHome_FAQ_топ15.docx`           | `e4d0834db83e12d705176ba65e201fe9bf118eceea80186dcc328bb7d093272b` |
| `reHome_База_статей_120.docx`     | `3e9db4cb0385c44679fe9687861fd62569bb1f4032ddeee9849137887d3ac05f` |

Любое расхождение sha256 при импорте → SystemExit (defence-in-depth
против тихих data drift'ов).

## Operations — bump seed version

При выгрузке нового набора .docx (новый месяц, изменённый контент):

1. Положить файлы локально, посчитать sha256:
   ```bash
   sha256sum reHome_FAQ_*.docx reHome_База_*.docx
   ```
2. Загрузить в bucket по новому пути:
   ```bash
   mc cp reHome_FAQ_*.docx     local-minio/kb-seed/articles/<NEW-DATE>/
   mc cp reHome_База_*.docx    local-minio/kb-seed/articles/<NEW-DATE>/
   ```
3. Обновить `SEED_VERSION` + `EXPECTED_SHA256` в
   `backend/scripts/import_kb_articles.py`.
4. Обновить таблицу выше.
5. Запустить `python -m scripts.import_kb_articles --dry-run` локально —
   проверить sha256 ok + parsing работает на новой структуре.

## Operations — re-import

Стандартный путь (использует MinIO defaults):

```bash
# env-vars из docker-compose.dev.yml / production secret manager:
#   MINIO_ENABLED=True
#   MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY
# + token админа в /tmp/.kb-token (короткоживущий JWT)

cd backend
python -m scripts.import_kb_articles
```

Override источника (например, локальная dev-копия):

```bash
python -m scripts.import_kb_articles \
    --faq file://$HOME/Downloads/reHome_FAQ_топ15.docx \
    --kb  file://$HOME/Downloads/reHome_База_статей_120.docx
```

Пропустить sha256 (только для bump seed-версии, до обновления pinned hash):

```bash
python -m scripts.import_kb_articles --faq file://... --kb file://... --no-verify-sha
```

## Why MinIO, not Git LFS

См. ADR-0027 — short version: MinIO уже в стеке (kb-files), весь in-РФ
(ФЗ-152), не раздувает clone'ы, .docx — это data а не code.
