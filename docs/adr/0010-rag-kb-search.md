# ADR-0010: RAG stack для kb-search — pgvector (Stage 1) → Qdrant (Stage 2)

## Статус

- [x] **Принято**
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-13
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** да, 2026-05-13 (PR #122)

### Решения по open questions (Архитектор, 2026-05-13)

1. **Embedding worker hosting**: отдельный k8s Deployment (CPU-bound,
   scale'ится независимо от gateway). НЕ sidecar.
2. **Re-embedding на model bump**: blue-green с `embedding_model_id`
   column. Dual-write в transition window, atomic switch при 100% coverage.
3. **Hardware**: CPU-only на старте. GPU когда (a) p95 query embedding
   >200ms или (b) initial reindex >2h.
4. **Launch corpus**: только articles. Documents (kb-files эпик не landed)
   и chat history (privacy review нужен) — отдельные ADR'ы.

## Контекст

Архитектура (`docs/architecture.md` line 29, 61, ADR-0001) задекларировала
`kb-search` как RAG-движок для AI-чата. Текущий чат (E3 epic, PR'ы
#63-71) отправляет пользовательский query прямо в LLM без retrieval —
ответы не привязаны к корпусу базы знаний, нет цитирования, hallucination
свободно.

CLAUDE.md «Технологический стек» line 122-124 уже задекларировал:
- pgvector — для векторного поиска (small/medium scale).
- Qdrant — для больших объёмов (kb-search).

ADR-0008 (ORM SQLAlchemy в gateway) line 114 упоминает pgvector
extension через миграции. Реальной integration пока нет — это решение
unblock'ает её.

Earlier (compact'нутая сессия): Архитектор выбрал «Без RAG (Recommended)»
для chat MVP. Это решение касалось **немедленной реализации в E3 chat**,
не отвергало RAG как направление. Архитектура (`kb-search` модуль) и
стек (pgvector/Qdrant) остались утверждёнными.

## Решение

**Two-stage approach** для RAG implementation.

### Stage 1: pgvector в существующем Postgres (immediate next step)

Расширяем существующий Postgres-kb (ADR-0008) через pgvector extension.
Articles уже имеют `search_vector` (Postgres FTS, GIN-индекс) — добавляем
параллельную `embedding vector(N)` column.

**Зачем**: нулевая новая infrastructure. pgvector — extension, не
отдельный сервис. Backup / replication / monitoring наследуется от
существующего Postgres. Уровень scale до ~100k chunks pgvector handles
comfortably (`<lists 256, hnsw m=16> + IVF + GiST/IVFFlat indexes`).

**Embeddings**: self-hosted, no external API (ФЗ-152). Конкретная модель —
[`intfloat/multilingual-e5-large`](https://huggingface.co/intfloat/multilingual-e5-large)
(~560M params, 1024-dim vectors, open-weights MIT, Russian + 100 other
langs). Inference через `sentence-transformers` библиотеку в собственном
worker'е (отдельно от gateway — не блокируем request loop). Альтернатива
поменьше: `intfloat/multilingual-e5-base` (~280M, 768-dim, чуть хуже
quality, в 2× быстрее).

**Chunking**: paragraph-based с overlap.
- Target chunk size: 512 токенов (≈ 2000 chars для русского).
- Overlap: 64 токенов (~12% — стандартная heuristic).
- Markdown headings preserve'ятся как separator hints — chunk boundaries
  по headings когда возможно.
- Code blocks (``` ```) НЕ разбиваются — лучше один большой chunk чем
  syntactically broken fragments.

**Retrieval — hybrid (BM25 + vector + RRF rerank)**:
1. Запрос параллельно в Postgres FTS (`ts_rank`) и vector similarity
   (`embedding <=> query_embedding`).
2. Каждый retriever возвращает top-30 candidates.
3. Reciprocal Rank Fusion: `score = Σ 1/(k + rank_i)` где k=60
   (стандартный default).
4. Top-10 from RRF → top-3 в prompt context.
5. ADR-0003: `WHERE access_level IN (...)` filter мандаторен в **обоих**
   queries (FTS и vector). Storage-level invariant.

**Citations**: каждый chunk хранит `(article_slug, chunk_index, char_offsets)`.
Chat response включает `citations: [{slug, chunk_index, snippet}]`. UI
рендерит как clickable refs → article detail с highlight.

**Не реализуем в Stage 1** (отложено):
- Query expansion / HyDE (генерация гипотетических ответов для лучшего
  retrieval'а).
- Cross-encoder reranker (slow + memory-heavy для MVP).
- Knowledge graph augmentation.
- Multi-turn conversational memory beyond chat session history.

#### Stage 1 deployment topology — provider selection

`EMBEDDING_PROVIDER` env (Settings.embedding_provider) выбирает между
`mock` и `hf`:

- **`mock`** (default для dev / CI / гейтвея до прод-cutover'а) —
  deterministic SHA-based, нет heavy deps. Использует фиксированный
  model_id `mock-v1` (НЕ `settings.embedding_model`) — fake vectors не
  должны share model_id с реальной prod-моделью, иначе blue-green
  invariant сломается при последующем switch на `hf`.

- **`hf`** — `intfloat/multilingual-e5-large` через
  `sentence-transformers`. ~1.5 GB PyTorch + ~2.3 GB model weights, не
  загружаются в main API контейнер (см. `requirements.txt` vs
  `requirements-rag.txt`). Используется в **dedicated indexer worker**
  Docker target. Main gateway работает с `mock` пока индексер не
  накопил production-grade vectors в Postgres и retrieval-side не
  переключился.

Wiring через `_build_provider(settings)` в `retrieval.py` — lazy
import HF-provider'а защищает от ImportError при отсутствии
`requirements-rag.txt` в API-контейнере.

Cutover sequence:
1. Indexer worker запускается с `EMBEDDING_PROVIDER=hf` → re-индексирует
   все статьи под новым `model_id` (parallel rows в `article_embeddings`).
2. Coverage >=100% (verified через `SELECT DISTINCT embedding_model_id
   FROM article_embeddings`) → flip gateway `EMBEDDING_PROVIDER=mock` →
   `hf`. Retrieval начнёт использовать real vectors.
3. После burn-in (24-48h) → cleanup mock vectors через
   `EmbeddingRepository.delete_by_model('mock-v1')`.

### Stage 2: Migration на Qdrant (триггер-based)

Переезжаем на Qdrant когда **любой** trigger срабатывает:

1. **Scale**: >100k chunks в indexed corpus OR >10 GiB vectors total.
2. **Latency**: p95 retrieval >300ms при текущем traffic (HNSW в pgvector
   плохо параллелится — Qdrant native concurrent).
3. **Operational**: нужны feature'ы Qdrant'а — payload filters с complex
   boolean, distributed sharding для multi-tenancy, snapshot-based backup
   independent от Postgres backup'а.

Migration path:
- Index структура (embedding + payload {slug, chunk_index, access_level,
  article_id}) совпадает в pgvector и Qdrant — payload schema reusable.
- Retrieval API stays the same (за абстракцией `SearchProvider` —
  `PgvectorProvider` → `QdrantProvider`).
- Re-embed НЕ нужно — vectors переносятся as-is через Qdrant import API.

ADR-XXXX (отдельный, когда trigger срабатывает) формализует Qdrant
deployment topology.

## Альтернативы

1. **OpenAI / Anthropic embeddings API** — отклонены ФЗ-152 (data
   residency). Embeddings = derived PII (если корпус содержит ПДн), не
   могут уходить за пределы РФ.

2. **Qdrant с Stage 1** — отклонена потому что (a) добавляет полноценный
   сервис (HA cluster, snapshot job, monitoring) без явной потребности
   на early scale, (b) увеличивает operational overhead в фазе когда
   корпус — десятки тысяч chunk'ов max. Bridge-pattern (pgvector now,
   Qdrant later) даёт лучшее combination time-to-market и
   future-proofing.

3. **Pure vector (без BM25 hybrid)** — отклонена потому что vector
   retrieval плохо handles исключительно lexical queries («какой
   parameter в `LLM_MAX_TOKENS`») и acronyms / numeric strings. Hybrid
   стабильнее на mixed queries.

4. **MeiliSearch / Elasticsearch как complement к pgvector** —
   отклонены потому что Postgres FTS уже работает (E2.5a #46) и
   достаточен для BM25-side hybrid'а. Зачем второй сервис когда есть
   первый.

5. **GraphRAG / entity-based retrieval** — отклонены для MVP. Корпус
   reHome (статьи, документы, карточки квартир) хорошо ложится на
   straightforward chunk-retrieval. GraphRAG имеет смысл при сильно
   relational корпусе (e.g., legal case law) — не наш профиль сейчас.

6. **Embedding model via vLLM** — vLLM поддерживает embeddings endpoint
   с правильной model, но смешивать generation + embedding в одной
   instance плохо (resource contention, memory pressure при concurrent
   workload'е). Separate sentence-transformers worker — cleaner.
   Compromise: можно посадить embedding model в одном vLLM instance в
   dev environment, prod — отдельно.

## Последствия

### Положительные

- **Zero new infrastructure для Stage 1**: только Postgres extension.
- **ADR-0003 invariant сохраняется**: access_level filter в both
  FTS+vector queries.
- **Citations**: chat ответы получают grounding в корпусе → меньше
  hallucination, лучше trust.
- **Russian-first quality**: multilingual-e5 — top-tier для русского
  на open-weights benchmarks.
- **Migration path explicit**: переход на Qdrant через bridge — не
  big-bang rewrite.

### Отрицательные / компромиссы

- **pgvector cost in Postgres**: embeddings таблица растёт быстро,
  Postgres backup'ы duplate'ятся. Mitigation: separate Postgres-kb
  schema `search` для embeddings, configurable backup retention. Or
  Move to Qdrant rано.
- **HNSW в pgvector**: index build долгий, не online (требует ANALYZE +
  rebuild при schema change). Acceptable для MVP scale, painful at
  >100k chunks. Это Stage 2 trigger.
- **Sentence-transformers worker** — новый компонент с CPU/GPU
  requirements. CPU-only inference multilingual-e5-large ~50ms на chunk,
  embedding в bulk OK. GPU нужен только если real-time query embedding
  становится bottleneck'ом.
- **Re-embedding на model change**: смена embedding model требует
  re-index corpus. Mitigation: versioned `embedding_model_id` column,
  поддержка multiple model versions parallel в transition window.

### Технические следствия

- New backend module: `backend/src/api/search/` (analogous to
  `articles/`, `webhooks/`).
- New Postgres migration: `0014_article_embeddings.py`:
  - `CREATE EXTENSION vector`.
  - Table `article_embeddings` (article_id FK, chunk_index, embedding,
    char_start, char_end, embedding_model_id, created_at).
  - HNSW index `(embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)`.
- New worker process: `kb-search-indexer` — listens на article create /
  update events (already wired in #92 via webhook dispatcher), chunks +
  embeds + upserts. Backlog: bulk reindex CLI для initial corpus.
- New endpoint: `POST /api/v1/search/articles` — retrieval-only, для
  internal use chat module'м (не публичный из коробки).
- Chat module integration: `messages` handler вызывает `search.retrieve(
  query, access_levels)` ДО LLM call, prepends top-3 chunks к prompt.
- New settings:
  - `RAG_ENABLED=false` (default — Stage 1 lands в off-state, явный flip).
  - `EMBEDDING_MODEL=intfloat/multilingual-e5-large`.
  - `EMBEDDING_DIM=1024`.
  - `RAG_TOP_K=10`, `RAG_CONTEXT_K=3`, `RAG_RRF_K=60`.
- Test coverage:
  - Unit: chunking, RRF fusion, access_level filter в vector query.
  - Integration: end-to-end query → retrieved chunks → LLM context →
    response с citations. Real Postgres + pgvector + small test corpus.
- ADR-0008 update: add note что pgvector landed.

## Открытые вопросы (отдельные follow-up'ы)

1. **Embedding worker hosting** — отдельный k8s deployment? Sidecar?
   Зависит от ADR-0011 prod-deploy topology.
2. **Re-embedding strategy** при model bump — atomic switch vs blue-green?
3. **Cost / hardware budget** для inference (CPU-only ok? GPU когда?)
4. **Корпус для launch**: только articles? + documents (когда kb-files
   landed)? + chat history (для personalization — отдельный privacy
   review)?

## Ссылки

- CLAUDE.md «Технологический стек» (line 122-124)
- ADR-0001 (platform architecture, kb-search reference)
- ADR-0003 (access_level invariant — критично для RAG-pipeline)
- ADR-0008 (ORM, pgvector упоминание)
- `docs/architecture.md` line 29, 61 (kb-search в diagrams)
- multilingual-e5: https://huggingface.co/intfloat/multilingual-e5-large
- pgvector: https://github.com/pgvector/pgvector
- Qdrant: https://qdrant.tech/
- RRF paper: https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
- Связанные ADR: ADR-0001, ADR-0003, ADR-0008.
