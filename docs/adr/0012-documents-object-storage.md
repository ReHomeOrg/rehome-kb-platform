# ADR-0012: Documents object storage — MinIO + signed URLs

## Статус

[ ] Предложено
[x] Принято
[ ] Заменено ADR-MMMM
[ ] Отклонено

- **Дата:** 2026-05-15
- **Автор:** Агент-Разработчик
- **Согласовано Архитектором:** да, 2026-05-15 (PR #211 `@architect approved`)

## Контекст

ПЗ §3.1-3.3 + API §3.4 описывают модуль документов (юридических и др.):
6 категорий A-F (от публичных оферт до regulator-correspondence),
multi-format (DOCX/PDF/HTML), хранение в MinIO с per-category иерархией
папок. Backend сейчас имеет:

- `GET /api/v1/documents` — list metadata (#177)
- `GET /api/v1/documents/{id}` — detail metadata (#177)
- `GET /api/v1/documents/{id}/files/{file_format}` — **501 Not Implemented**

API §3.4 спецификация:

> Скачать файл документа. format ∈ {docx, pdf, html}. Возвращает 302
> Redirect на временный signed URL MinIO с TTL 5 минут.

> POST /api/v1/documents/{id}/files — Multipart upload файла к существующему
> документу. Возвращает version_id.

ADR-0001 (stack) утвердил MinIO как S3-совместимое объектное хранилище.
ADR-0003 §3 (storage-level enforcement) утвердил: «MinIO: signed URL с
TTL только после проверки прав» — application gate'ит, MinIO не доверяет.

Открытые вопросы:
- SDK choice (boto3 vs minio-python).
- Bucket strategy: single vs per-confidentiality.
- Key/path layout: матчить hierarchy из ПЗ §3.2?
- Upload flow: proxy multipart через FastAPI или direct-to-MinIO presigned PUT?
- Audit invariants — какие события писать.
- Test strategy — moto (mock) или MinIO docker для integration.

## Решение

### 1. SDK — `minio` (minio-python) официальный

- Версия `minio>=7.2`, добавляется в `backend/pyproject.toml`.
- Causes vs boto3:
  - lighter dep tree (~3 MB vs boto3 ~30 MB)
  - MinIO-vendored, наследует server-side roadmap
  - explicit (typed) presigned URL API без boto3-magic
- Cons: vendor lock (если уйдём на AWS S3, потребуется boto3 swap —
  но прямой S3 API через minio-python тоже работает, urgent проблема — нет).

### 2. Bucket — single bucket `rehome-kb-files`

- Single bucket, internal organization по prefix matching ПЗ §3.2 hierarchy:
  - `legal/external/<doc_id>/<version>/<format>.<ext>`
  - `legal/contracts/<year>/<user_uuid>/<doc_id>/<version>/...`
  - `legal/partners/<counterparty>/...`
  - `legal/internal/`, `legal/regulators/`, `legal/templates/`
  - `legal/_archive/`
- Bucket access policy — `private` (no anonymous). Все access через
  presigned URL backend'ом.
- Per-confidentiality bucket'ы (PUBLIC / INTERNAL / RESTRICTED) —
  отвергнуто: усложняет lifecycle, нет security win (signed URL TTL
  всё равно главный gate; bucket-level ACL — only secondary).

### 3. Storage key schema

```
legal/<category_subdir>/<doc_id>/<version_int>/<format>.<ext>
```

Where `category_subdir` mapping:
| category | subdir |
|---|---|
| A | external |
| B | contracts/<year>/<user_uuid?> |
| C | partners/<counterparty_slug> |
| D | internal |
| E | regulators |
| F | templates |

`version_int` — DB `documents.version` (string в TZ; для key используем
slugified version или auto-increment integer — TODO в implementation).

`format ∈ {docx, pdf, html}` strictly enforced.

### 4. Signed URL TTL — 5 минут (TZ)

- `SIGNED_URL_TTL_SECONDS = 300` config constant.
- На каждый GET /files/{format} backend generates fresh URL (no caching).
- Client follows 302 within TTL window; иначе → reload page → new URL.

### 5. Upload flow — **proxy multipart via FastAPI**

POST /api/v1/documents/{id}/files принимает `UploadFile` через
FastAPI multipart, stream'ит в MinIO `client.put_object()`.

**Не direct-presigned-PUT** потому что:
- Backend hash'ит content для integrity (`Content-MD5` header) — direct upload
  обошёл бы checksum.
- Application audit_log row пишется ATOMIC с записью в `documents.files`
  JSONB — direct upload требовал бы webhook-callback от MinIO (S3 Event
  Notification config), что сложнее.
- Anti-virus / PII scan placeholder — backlog hook для future ADR.

Cons: ограничивает upload через bandwidth backend pod. Ставим request
size limit (`MAX_UPLOAD_BYTES=50_000_000` = 50 MB), для bigger uploads
— backlog (multipart-init flow, ADR будущего).

### 6. Audit invariants

Каждая operation пишет audit_log:

| Action | Resource | Metadata |
|---|---|---|
| `documents.file.uploaded` | document | `{format, version, size_bytes, content_md5}` |
| `documents.file.downloaded` | document | `{format, version}` |
| `documents.file.archived` (lifecycle) | document | `{format, version, reason}` |

Metadata НЕ содержит content / filename (анти-leak PII). Только
machine-level info.

### 7. Error responses

| Backend state | HTTP status |
|---|---|
| Document not found / no scope | 404 (mask, ADR-0003) |
| Format not requested (`docx` запросили на HTML-only doc) | 404 |
| MinIO unreachable | 503 + `Retry-After: 10` |
| MinIO returned 5xx | 502 |
| Upload exceeds MAX_UPLOAD_BYTES | 413 |
| Invalid multipart | 422 |

### 8. Test strategy

- **Unit**: mock MinIO client (`monkeypatch repo.minio.put_object`), assert
  audit + DB writes.
- **Integration**: MinIO docker container в `docker compose` (test profile),
  существует ли уже — TBD; если нет, добавить compose definition. Полный
  upload + download + audit roundtrip.
- **CI**: integration job уже имеет Postgres + Keycloak в compose; добавим
  MinIO service.

## Альтернативы

1. **boto3 вместо minio-python** — отклонено: heavier deps, less idiomatic для
   MinIO server features (no real win если AWS S3 swap не на горизонте).

2. **Per-confidentiality buckets** — отклонено: усложняет lifecycle (3 bucket
   policy конфигов вместо одного), нет security win (signed URL ставит TTL
   gate; bucket ACL — secondary).

3. **Direct presigned PUT upload** — отвергнуто: нельзя гарантировать audit
   row atomic с DB write, требует S3 Event Notification webhook config.
   Откладываем до multipart-init flow для very large uploads (ADR будущего).

4. **Nextcloud вместо MinIO** — ПЗ §3.2 упоминает «MinIO/Nextcloud»; MinIO
   выбран потому что S3 API совместим (vendor lock минимальный) и lower
   ops surface (нет HTML / iCal / WebDAV которые не нужны).

## Последствия

### Положительные

- Backend полностью контролирует access (no shared-secret bucket policies
  — все через signed URL).
- Audit trail полный — нет obscure download без log row.
- Single SDK, single bucket — простая ops surface для запуска.

### Отрицательные / компромиссы

- Upload bandwidth ограничен backend pod'ом (50 MB ceiling приемлем для
  legal docs; для будущих больших файлов — multipart-init flow).
- Зависимость от MinIO availability — DOC requires fallback к 503/502
  без data loss.

### Технические следствия

- New backend dependency: `minio>=7.2`.
- New env: `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`,
  `MINIO_BUCKET=rehome-kb-files`, `MINIO_SECURE=true|false`.
- Secrets storage per ADR-0009 (SOPS+age).
- Docker compose adds MinIO service для local dev + integration tests.
- Backlog: per-format conversion (DOCX → PDF, HTML rendering) — отдельный
  ADR. Сейчас upload `format` именно как загружен; conversion deferred.
- Backlog: lifecycle policy (5-year archive из ПЗ §3.2) — отдельная
  migration / cron.

## Implementation phases

1. **Phase A — read path** (GET /files/{format}):
   - MinIO client wrapper module.
   - Repository extension: lookup file by (doc_id, version, format).
   - Router replace 501 with 302 + signed URL.
   - Audit log on download.
   - Unit tests (mocked MinIO).
   - Integration test (real MinIO docker).

2. **Phase B — write path** (POST /files):
   - Multipart upload handler с size limit.
   - Storage key compute helper.
   - Repository upsert `documents.files` JSONB entry с version increment.
   - Audit log on upload.
   - Unit + integration tests.

3. **Phase C — admin lifecycle** (out of scope для initial PR):
   - Archive endpoint (`POST /files/{format}/archive`).
   - Bulk migration script.
   - 5-year retention cron.

Phase A and B as separate PRs (sequential cubes), Phase C — backlog.

## References

- ПЗ «База знаний v1.4» §3.1-3.3
- API §3.4 (line 351 spec)
- ADR-0001 (stack)
- ADR-0003 (access_level filter on storage)
- ADR-0009 (secrets management — MinIO creds)
