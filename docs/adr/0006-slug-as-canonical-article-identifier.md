# ADR-0006: Slug как канонический идентификатор статей в API

## Статус

- [x] **Принято**
- **Дата:** 2026-05-11
- **Автор:** Агент-Разработчик (Claude Code) под управлением Архитектора Evgeniy
- **Согласовано Архитектором:** да, 2026-05-11 (комментарий Issue #7)

## Контекст

При миграции `04_openapi.yaml` к OpenAPI 3.1-syntax (Issue #7, follow-4
из post-hoc audit Проверяющего) обнаружен path conflict в путях
ресурса Article:

- `GET /api/v1/articles/{slug}` — чтение по slug (для SEO-URL help-центра)
- `PUT /api/v1/articles/{id}` — полное обновление по UUID
- `PATCH /api/v1/articles/{id}` — частичное обновление по UUID
- `DELETE /api/v1/articles/{id}` — архивация по UUID
- `GET /api/v1/articles/{id}/history` — история версий по UUID

Спецификация OpenAPI (3.0 и 3.1) запрещает несколько путей с одинаковой
структурой шаблона, даже если имена параметров различаются. Два пути
вида `/articles/{X}` неотличимы на уровне маршрутизации, поэтому
конфликт `{slug}` vs `{id}` — нарушение стандарта, на которое redocly
lint справедливо ругается.

Решение принципиально, потому что влияет на:
- Все 53 endpoint'а (через единообразие URL-паттернов для всех ресурсов
  модуля kb)
- SDK-генерацию (`openapi-typescript`, `openapi-python-client` и т.д.)
- SEO help-центра (rehome.one/articles/<slug>)
- Стабильность admin-скриптов и интеграций rehome.one

## Решение

Принят принцип **«slug — канонический идентификатор статьи в API»**.
Все операции ресурса Article (`GET / PUT / PATCH / DELETE /
GET .../history`) используют параметр `slug` в URL. UUID `id` остаётся
в теле сущности `Article` для server-side ссылок (например,
`AuditLogEntry.entity_id`, `Webhook.related_article_id`), но не
используется в публичном API как идентификатор.

Конкретные пути v1.0:

| Метод | Путь | operationId |
|---|---|---|
| GET | `/api/v1/articles/{slug}` | `getArticleBySlug` |
| PUT | `/api/v1/articles/{slug}` | `replaceArticle` |
| PATCH | `/api/v1/articles/{slug}` | `patchArticle` |
| DELETE | `/api/v1/articles/{slug}` | `archiveArticle` |
| GET | `/api/v1/articles/{slug}/history` | `getArticleHistory` |

Slug-параметр валидируется по pattern `^[a-z0-9-]+$` (lowercase ASCII +
цифры + дефисы), уникален на уровне БД, формируется автоматически из
поля `title` через slugify при создании статьи (логика реализации — в
E4 — Write для редакторов).

При rename статьи (изменение `title`) — slug может измениться, поэтому
требуется механизм **slug-alias**: таблица соответствий старый slug →
новый slug с автоматическим HTTP-redirect 301 на канонический URL.
Реализация slug-alias — часть E4 (тикет создаётся при реализации E4).
До запуска E4 — slug является неизменным после создания (без UI для
rename).

## Альтернативы

1. **Все операции на `{id}` (UUID)** — отклонено: ломает SEO-дружелюбные
   URL help-центра, делает публичные URL нечитаемыми
   (`/articles/7b3a8f1e-...`), GET по slug превращался бы в
   `?slug=...` query parameter — это менее идиоматично.

2. **Раздельные префиксы (`/articles/by-slug/{slug}` +
   `/articles/{id}`)** — отклонено: уродливый SEO-URL, два URL для
   одной сущности усложняют клиентскую логику и SDK.

3. **Раздельные namespaces (`/articles/{slug}` публично +
   `/admin/articles/{id}` для админа)** — отклонено: scope-расширение
   API, требует параллельной реализации в backend, ломает единый
   контракт.

## Последствия

### Положительные

- Spec становится lint-clean по OpenAPI 3.1 (`redocly lint` → 0 errors)
- Единый URL-паттерн для всех операций ресурса — проще SDK, проще
  документация
- SEO-friendly URLs сохраняются естественно
- Slug читаем в логах, audit_log, error messages — упрощает поддержку

### Отрицательные / компромиссы

- Slug — менее стабильный идентификатор, чем UUID; при rename статьи
  старый URL ломается без alias-таблицы (см. требование slug-alias
  выше)
- Admin-скрипты должны знать slug (а не UUID, который проще
  copy-paste'ить из БД). Митигация: в админке выводить slug рядом с
  id; при необходимости — отдельная админ-команда «найти статью по
  UUID и показать slug»
- slug-pattern `^[a-z0-9-]+$` ограничивает символы — кириллические
  slug'и невозможны (как у Wikipedia они латинские). Это
  компромисс ради чистого URL; для русскоязычных названий статей —
  транслитерация через стандартную библиотеку (`python-slugify` или
  аналог) на этапе создания

### Технические следствия

- В `04_openapi.yaml` 5 path-операций ресурса Article переименованы
  на `{slug}`; блок `/api/v1/articles/{id}:` удалён; PUT/PATCH/DELETE
  перенесены под `/api/v1/articles/{slug}:`
- При реализации в E4 — в Django ORM модели `Article` добавляется
  `slug = models.SlugField(max_length=200, unique=True)`
- При реализации в E4 — добавляется модель `ArticleSlugAlias`
  (`old_slug → article_id`) и middleware/view для 301-redirect
- В админке kb-staff (E5/E6) добавляется UI поле slug рядом с UUID
- SDK для TypeScript / Python генерируется заново после mergre PR #7

### Не пересматривается на этом ADR

Аналогичный вопрос для других ресурсов:
- `Document` использует UUID (`/documents/{id}`) — slug не имеет
  смысла для юридического документа
- `PremisesCard` использует `premises_id` (UUID) — slug не имеет
  смысла для квартиры
- `Collaborator` использует UUID — slug не имеет смысла для
  партнёра

Slug-канонизация — узкое решение под ресурс **Article**, где
SEO-фактор критичен. Для других ресурсов остаётся UUID как
identifier.

## Ссылки

- Issue: https://github.com/rehome-one/rehome-kb-platform/issues/7
- ПЗ: «API базы знаний v1.3» раздел 1.3 (OpenAPI 3.1 источник
  истины), раздел 3.2 (Articles endpoints)
- OpenAPI: `docs/handoff/01_postanovka/04_openapi.yaml` (пути
  `/api/v1/articles/...`)
- Связанные ADR: ADR-0005 (FastAPI gateway)
- Post-hoc audit Проверяющего, finding F2.6 (P1)
- Внешние материалы:
  - [OpenAPI 3.1 spec on Path Templating](https://spec.openapis.org/oas/v3.1.0#path-templating)
  - [Stack Overflow: identical paths in OpenAPI](https://stackoverflow.com/q/57835770)
