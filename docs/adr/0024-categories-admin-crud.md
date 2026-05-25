# ADR-0024: Categories admin CRUD — endpoint surface + cycle detection

## Статус

- [x] **Предложено** (awaiting Architect approval)
- [ ] Принято
- [ ] Заменено ADR-MMMM
- [ ] Отклонено

- **Дата:** 2026-05-25
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** **нет**, awaiting approval

## Контекст

Категории articles (kb-wiki taxonomy) — иерархическое дерево
`categories.parent_id → categories.id`. Сейчас:

- **Read** уже implemented: `GET /api/v1/categories` возвращает дерево
  с article_count per scope (ADR-0003 invariant). Frontend admin
  показывает.
- **Write** отсутствует. Создание / переименование / удаление категории
  возможно только через прямой SQL или alembic seed migration.
- **Article.category** хранится как FK-less string match (`articles.category
  = categories.slug`). Если admin удалит категорию — orphan articles.

В `categories/models.py:5` есть backlog маркер: «Полное cycle-detection
(A→B→A) — backlog admin CRUD эпика». DB CHECK constraint защищает только
от self-reference (`parent_id <> id`).

Бизнес-требование (ПЗ «База знаний v1.4» §5): admin должен мочь
управлять taxonomy без deploy'а / DB access. Конкретные сценарии:
- Добавить новую категорию (`сервисный-платёж` под `Финансы`).
- Переименовать категорию (title; slug менять не безопасно — это identifier).
- Переместить под другой parent.
- Архивировать (не удалять — orphan articles).

## Решение

**Recommend Вариант B** (full admin CRUD с cycle detection + soft-delete).
Awaits Architect approval перед implementation.

Endpoint surface (если B принят):
- `POST /admin/categories` — create (slug + title + parent_id).
- `PATCH /admin/categories/{id}` — update (title / description / parent_id).
- `DELETE /admin/categories/{id}` — soft-delete (archive flag).
- `GET /admin/categories/{id}` — карточка (для UI edit form).

RBAC: staff_admin (STAFF + LEGAL). Same gate как других admin write
endpoints.

Cycle detection: при PATCH parent_id выполняется обход вверх по
parent_id chain до root или collision с current node id — если
встречаем target_id → 422 «would create cycle». Implemented в repo на
read-then-validate basis (committed advisory lock на parent_id chain
не нужен — categories low-write).

Soft-delete instead hard-delete: вводит `archived_at TIMESTAMPTZ NULL`
column. `articles.category` остаётся valid string; admin UI показывает
«архивированы» badge но не блокирует article.category lookup. Hard
delete — backlog (требует Article migration или FK enforcement).

## Альтернативы

### Вариант A — Только POST (минимальный)

Только `POST /admin/categories` (create). PATCH/DELETE остаются manual
(direct SQL или alembic migration).

**Pros:**
- Minimal surface (1 endpoint vs 4).
- Cycle detection — N/A (создание новой категории не создаёт cycle).
- Меньше тестов.

**Cons:**
- Admin не может переименовать категорию без deploy'а.
- Не закрывает реальный admin pain (rename / parent change).
- `cycle-detection backlog` маркер остаётся открытым.

**Отклонено**: не решает реальную проблему.

### Вариант B — Full CRUD с cycle detection + soft-delete (recommended)

Описан выше.

**Pros:**
- Полная admin autonomy на taxonomy.
- Cycle detection закрыт.
- Soft-delete preserves articles без data loss.
- OpenAPI coverage 98 → 102 (4 new endpoints).
- Reuses existing patterns: keyset cursor, MFA gate, audit log.

**Cons:**
- Substantial scope: backend repo + router + schemas + migration
  (`archived_at` column) + 4 endpoints + tests + frontend UI.
- Cycle detection — extra SQL passes на каждый PATCH (acceptable; low-write).

**Recommend.**

### Вариант C — CRUD без soft-delete (hard-delete + RESTRICT FK)

Implement FK from `articles.category` → `categories.slug` с
`ondelete=RESTRICT`. Hard delete blocks если есть references.

**Pros:**
- Чище semantically.
- Нет lingering archived categories.

**Cons:**
- Требует data migration: backfill / cleanup orphan `articles.category`
  значений (которые могут существовать после category seed migration'а
  без FK).
- Articles массовая operation deletion blocked силой FK — admin'у нужен
  bulk reassignment endpoint для articles перед deletion.
- Breaking change для articles persistence (FK добавляется впервые).

**Отклонено**: out of scope для категорий CRUD epic; FK migration —
отдельный backlog (когда мы реально решим что category — FK, не string).

## Последствия (если B принят)

### Положительные

- Admin может управлять taxonomy через UI без deploy'а.
- Cycle detection закрывает known gotcha из category model docstring.
- Soft-delete preserves data integrity (no orphan articles).
- Audit trail на category creation / rename / archive (compliance).
- Pattern reuse: keyset cursor list, MFA не нужен (категории — не
  security-sensitive), staff_admin RBAC, idempotency-key для POST.

### Отрицательные / компромиссы

- Schema change: `archived_at` column + alembic migration.
- `GET /categories` (public) теперь должен фильтровать archived
  (`archived_at IS NULL`) — small behavior change.
- `article_count` aggregation должна skip archived categories — adjust
  `CategoryRepository.list_tree` accordingly.
- Cycle detection требует SQL passes — sub-millisecond на realistic
  taxonomy (~100 categories deep), но добавляет latency.

### Технические следствия

**Migration:**
- `0030_categories_archived_at`: ADD COLUMN `archived_at TIMESTAMPTZ
  NULL` + partial index `WHERE archived_at IS NULL` для tree queries.

**Backend:**
- `categories/admin_repository.py`: new `CategoryAdminRepository` с
  CRUD + cycle detection.
- `categories/admin_router.py`: 4 endpoints prefix `/admin/categories`.
- `categories/admin_schemas.py`: `CategoryCreate`, `CategoryPatch`,
  `CategoryView` (extends existing read schema).
- Update existing `CategoryRepository.list_tree` для skip archived.
- Audit actions: `admin.category.created` / `.updated` / `.archived`.

**Tests:**
- Unit: cycle detection (A→B→A trap, deep chain, self via PATCH),
  RBAC (staff_admin only, non-admin → 403), audit, idempotency-key.
- Integration: full CRUD lifecycle.

**OpenAPI:**
- 4 new operations + obvious schemas.

**Frontend:**
- Admin UI `/admin/categories` — tree view + add/edit/archive
  controls. Estimated ~200 LOC TSX.

**Frontend impact на existing `GET /categories`** — archived categories
не возвращаются (defaults `archived_at IS NULL` filter). Public кода
не ломает (никакой UI не показывает archived).

## Открытые вопросы для Архитектора

1. **Approve Вариант B** (full CRUD + soft-delete) — рекомендуется?
2. **Slug immutable?** Изменение slug ломает articles.category строку.
   Предлагаю: slug READ-ONLY (только PATCH title / description / parent_id).
3. **MFA требуется?** Categories — не PII / not security-sensitive.
   Предлагаю: staff_admin gate БЕЗ step-up MFA (как PATCH /admin/users).
4. **Cycle detection — реализовать на DB-уровне** (recursive CTE
   trigger) **или на app-уровне** (Python recursive check)?
   Предлагаю: app-уровень — категорий мало (~100), simpler, тестируемее.
5. **Frontend — отдельный PR или часть backend PR?** Предлагаю:
   разделить (backend как Slice 1, frontend Slice 2).

## Implementation gating

PR с реализацией создаётся ТОЛЬКО ПОСЛЕ ADR approve. Без approve'а
рассматривается как design-violation per CLAUDE.md §9.

## Ссылки

- ПЗ: «База знаний v1.4» §5 (taxonomy)
- Связанные ADR: ADR-0003 (storage-level filter; categories tree
  reuses pattern), ADR-0019 (admin config endpoints baseline)
- Existing code: `backend/src/api/categories/{models,repository,
  router}.py`, `backend/alembic/versions/20260512_*_initial_articles.py`
  (category column FK-less)
