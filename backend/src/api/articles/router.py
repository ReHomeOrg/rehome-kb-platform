"""FastAPI router для `/api/v1/articles/*`.

E2.1 — только `GET /articles/{slug}`. Дальнейшие операции (list, поиск,
write) добавляются в следующих эпиках через дополнительные методы router.
"""

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response, status

from src.api.articles.audit import (
    log_article_archived,
    log_article_created,
    log_article_updated,
)
from src.api.articles.authorization import ensure_can_write_access_level
from src.api.articles.cursor import (
    decode_cursor,
    decode_score_cursor,
    encode_cursor,
    encode_score_cursor,
)
from src.api.articles.etag import (
    DEFAULT_CACHE_HEADERS,
    compute_article_etag,
    compute_history_etag,
)
from src.api.articles.repository import ArticleRepository, get_article_repository
from src.api.articles.schemas import (
    ArticleHistoryResponse,
    ArticleInput,
    ArticlePatch,
    ArticleResponse,
    ArticlesListResponse,
    ArticlesSearchResponse,
    ArticleSummary,
    ArticleVersionResponse,
    PaginationInfo,
    SearchHit,
    SearchInput,
)
from src.api.audit import (
    ACTION_ARTICLES_ARCHIVED,
    ACTION_ARTICLES_CREATED,
    ACTION_ARTICLES_UPDATED,
    RESOURCE_ARTICLE,
    AuditRepository,
    SecurityEventType,
    SecuritySeverity,
    get_audit_repository,
    report_security_event,
)
from src.api.auth.dependency import (
    get_current_access_levels,
    require_access_level,
    require_authenticated,
)
from src.api.auth.exceptions import ForbiddenError, UnauthorizedError
from src.api.auth.scope import AccessLevel
from src.api.config import get_settings
from src.api.idempotency import IdempotencyResult, process_idempotency_key
from src.api.search.indexer import IndexerService, get_indexer_service
from src.api.webhooks.dispatcher import (
    WebhookEventDispatcher,
    get_webhook_event_dispatcher,
)

# Slug pattern из OpenAPI / ADR-0006: lowercase ASCII, цифры, дефисы.
# 1..200 символов, не пустой. Защищает от path-injection и SQL-сюрпризов
# (хотя ORM параметризует — это defence-in-depth).
SLUG_PATTERN = r"^[a-z0-9-]+$"

# Tags filter constraints (см. Issue #34):
# - max 10 тегов на запрос (anti-DoS на JSONB поиск)
# - max 50 символов на тег (sensible upper bound, OpenAPI пример
#   `сервисный-платёж` — 16 chars)
# Случай повторных запятых / пробелов — нормализуется (strip + filter empty).
# Case-sensitive: `Договор != договор`; нормализация — backlog.
# Tag с запятой внутри не поддерживается (CSV-конфликт).
TAGS_MAX_COUNT = 10
TAGS_MAX_LENGTH = 50


def _parse_tags(raw: str | None) -> list[str] | None:
    """CSV → list[str] с dedupe + strip + drop empty.

    None / пустая строка / только-пробелы → None (фильтр не применяется).
    >10 элементов или >50 символов → HTTPException 422 (без эха user-input).
    """
    if not raw or not raw.strip():
        return None
    items = [t.strip() for t in raw.split(",")]
    deduped: list[str] = []
    for t in items:
        if t and t not in deduped:
            deduped.append(t)
    if not deduped:
        return None
    if len(deduped) > TAGS_MAX_COUNT:
        raise HTTPException(
            status_code=422,
            detail=f"Too many tags (max {TAGS_MAX_COUNT})",
        )
    for t in deduped:
        if len(t) > TAGS_MAX_LENGTH:
            # Не echo'им user-input в detail (длина инкорпорируется через
            # message, но не сам tag content).
            raise HTTPException(
                status_code=422,
                detail=f"Tag exceeds max length ({TAGS_MAX_LENGTH} chars)",
            )
    return deduped


async def _ensure_write_target_or_report_bypass(
    *,
    target: AccessLevel,
    access_levels: frozenset[AccessLevel],
    actor_sub: str,
    slug: str,
    method: str,
    dispatcher: WebhookEventDispatcher,
) -> None:
    """ADR-0003 target-check + #223 security-event emission.

    Если writer пытается установить target access_level, которого у него
    самого нет — fire `audit.security_event` (event_type=auth.target_bypass)
    и propagate'им оригинальный 403. Event эмитится ДО raise — это observable
    «attempt», даже если HTTP-ответ уйдёт как 403.

    Не пишем в audit_log (он трекает успешные state-changes; неуспешная
    попытка → отдельный webhook outbox path для SIEM/alerting).
    """
    try:
        ensure_can_write_access_level(target, access_levels)
    except ForbiddenError:
        await report_security_event(
            dispatcher,
            event_type=SecurityEventType.AUTH_TARGET_BYPASS,
            severity=SecuritySeverity.WARNING,
            details={
                "actor_sub": actor_sub,
                "method": method,
                "slug": slug,
                "target_access_level": target.value,
                # `current_levels` нужен для post-hoc analysis ("what did
                # the user have"); sorted чтобы log diff'ы deterministic.
                "current_access_levels": sorted(level.value for level in access_levels),
            },
        )
        raise


async def _maybe_dispatch_article_status_event(
    dispatcher: WebhookEventDispatcher,
    article: Any,
    old_status: str | None,
) -> None:
    """Fire matching webhook event на основе status-перехода (E5.3 #91).

    - `old_status is None` означает create (POST /articles): fire
      `article.published` если status='PUBLISHED'.
    - `old_status != article.status`: fire transition event если новое
      состояние — PUBLISHED или ARCHIVED.

    `article.updated` для любого edit'а — отдельный helper
    `_dispatch_article_updated` (вызывается из PUT/PATCH рядом с этим).
    """
    new_status = article.status
    if old_status == new_status:
        return
    if new_status == "PUBLISHED":
        await dispatcher.dispatch(
            event_type="article.published",
            payload={
                "slug": article.slug,
                "title": article.title,
                "access_level": article.access_level,
                "published_at": (article.published_at or article.updated_at).isoformat(),
            },
        )
    elif new_status == "ARCHIVED":
        await dispatcher.dispatch(
            event_type="article.archived",
            payload={
                "slug": article.slug,
                "title": article.title,
                "archived_at": article.updated_at.isoformat(),
            },
        )


async def _dispatch_article_updated(
    dispatcher: WebhookEventDispatcher,
    article: Any,
    *,
    changed_fields: list[str],
) -> None:
    """Fire `article.updated` (ТЗ §5.1) для любого edit'а.

    Ortогонален transitions из `_maybe_dispatch_article_status_event` —
    subscriber'ы могут подписаться независимо на «изменилось хоть что-то»
    vs «status вышел в PUBLISHED». В PUT/PATCH вызываются оба helper'а;
    дублирования не будет, т.к. они dispatch'ат разные event_type.

    `changed_fields` — для PATCH derives from `payload.model_dump(exclude_unset=True)`;
    для PUT передаём `["full_replacement"]` (PUT semantics — full body
    replacement, granular diff не tracked'ится дешевле re-fetch'а).

    Empty `changed_fields` — no-op (защита от degenerate PATCH с empty body).
    """
    if not changed_fields:
        return
    await dispatcher.dispatch(
        event_type="article.updated",
        payload={
            "slug": article.slug,
            "title": article.title,
            "access_level": article.access_level,
            "status": article.status,
            "changed_fields": changed_fields,
            "updated_at": article.updated_at.isoformat(),
        },
    )


async def _maybe_index_article(
    indexer: IndexerService,
    article: Any,
) -> None:
    """RAG indexer trigger (#130). Gated на `RAG_ENABLED` env flag.

    Decision matrix:
    - `status == 'PUBLISHED'` → index (upsert chunks).
    - `status != 'PUBLISHED'` (DRAFT / ARCHIVED) → remove existing
      embeddings, если были. Это важно: статья переход'нулась в DRAFT —
      её нельзя retrieve'ить через RAG → cleanup.

    `RAG_ENABLED=False` (default) → no-op.

    Errors swallowed внутри IndexerService (article transaction уже
    commit'нулась, RAG side-effect не должен fail'ить request).
    """
    if not get_settings().rag_enabled:
        return
    if article.status == "PUBLISHED":
        await indexer.index_article(
            article_id=article.id,
            body_markdown=article.body_markdown,
        )
    else:
        await indexer.remove_article(article.id)


async def _maybe_remove_article_by_slug(
    indexer: IndexerService,
    slug: str,
) -> None:
    """RAG indexer slug-based remove (DELETE handler — id не доступен).
    Same gating semantics что и `_maybe_index_article`.
    """
    if not get_settings().rag_enabled:
        return
    await indexer.remove_article_by_slug(slug)


router = APIRouter(prefix="/articles", tags=["Articles"])


@router.get(
    "",
    response_model=ArticlesListResponse,
    summary="Список статей с фильтрами и cursor-пагинацией",
    responses={
        400: {"description": "Невалидный cursor"},
        422: {"description": "Невалидные query-параметры (limit/audience/...)"},
    },
)
async def list_articles(
    category: str | None = Query(default=None, max_length=100),
    audience: str | None = Query(default=None, max_length=16),
    language: str | None = Query(default=None, max_length=8),
    tags: str | None = Query(
        default=None,
        max_length=600,
        description=(
            "Список тегов через запятую (AND-semantics). Пробелы strip'аются,"
            " дубликаты удаляются. Max 10 тегов, max 50 символов на тег."
        ),
    ),
    cursor: str | None = Query(
        default=None,
        description="Opaque pagination cursor; не парсится клиентом.",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ArticleRepository = Depends(get_article_repository),
) -> ArticlesListResponse:
    """Отдаёт страницу опубликованных статей с фильтрацией по scope.

    ADR-0003: 404-маскировка тут не применяется — для list пустой массив
    нормален и не утекает информацию о существовании ресурсов другого
    scope (фильтр `access_level IN (...)` отсекает на SQL).
    """
    if not access_levels:
        raise UnauthorizedError(detail="No access levels resolved")

    decoded_cursor = decode_cursor(cursor) if cursor else None
    parsed_tags = _parse_tags(tags)

    rows, has_more = await repo.list_filtered(
        access_levels,
        category=category,
        audience=audience,
        language=language,
        tags=parsed_tags,
        cursor=decoded_cursor,
        limit=limit,
    )

    cursor_next: str | None = None
    if rows and has_more:
        last = rows[-1]
        cursor_next = encode_cursor(last.updated_at, last.id)

    return ArticlesListResponse(
        data=[ArticleSummary.model_validate(row) for row in rows],
        pagination=PaginationInfo(cursor_next=cursor_next, has_more=has_more),
    )


@router.get(
    "/{slug}",
    summary="Получить статью по slug",
    responses={
        200: {"description": "Статья"},
        304: {"description": "Не изменилась с last ETag"},
        404: {"description": "Статья не существует или недоступна текущему scope"},
    },
)
async def get_article_by_slug(
    response: Response,
    slug: str = Path(
        ...,
        min_length=1,
        max_length=200,
        pattern=SLUG_PATTERN,
        description="Канонический идентификатор статьи (ADR-0006)",
    ),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ArticleRepository = Depends(get_article_repository),
) -> Any:
    """Отдаёт опубликованную статью с фильтрацией по access_level.

    ADR-0008: router принимает `ArticleRepository`, не `AsyncSession` —
    storage-level фильтр (ADR-0003) защищён type-system'ом от случайного
    обхода через прямой `session.execute(...)`.

    Маскировка: если статья существует, но scope её не видит, возвращаем 404
    (не 403) — клиент не должен узнавать факт существования закрытого ресурса.

    E5.2: ETag header + `If-None-Match` → 304 Not Modified (conditional GET).
    `Vary: Authorization` — shared proxy не leaks STAFF body anonymous'у.
    ETag computes ПОСЛЕ source check — не утекает visibility.
    """
    if not access_levels:
        # Defence-in-depth: compute_access_levels всегда возвращает минимум
        # {PUBLIC}, попадание сюда — баг scope-логики. Лучше 401 чем 500.
        raise UnauthorizedError(detail="No access levels resolved")

    article = await repo.get_by_slug(slug, access_levels)
    if article is None:
        # 404 не 403 (ADR-0003 masking).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )

    # E5.2: compute ETag после source check (не leak visibility).
    etag = compute_article_etag(article)
    if if_none_match is not None and if_none_match == etag:
        # 304 Not Modified: только headers, no body.
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={"ETag": etag, **DEFAULT_CACHE_HEADERS},
        )

    response.headers["ETag"] = etag
    for k, v in DEFAULT_CACHE_HEADERS.items():
        response.headers[k] = v
    return ArticleResponse.model_validate(article)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ArticleResponse,
    summary="Создать статью (требует scope ≥ staff_support)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope или access_level недоступен writer'у"},
        409: {"description": "Slug уже существует"},
        422: {"description": "Невалидный payload"},
    },
)
async def create_article(
    payload: ArticleInput,
    response: Response,
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: ArticleRepository = Depends(get_article_repository),
    idempotency: IdempotencyResult = Depends(process_idempotency_key),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    indexer: IndexerService = Depends(get_indexer_service),
) -> Any:
    """Создаёт статью.

    Авторизация (двух-уровневая):
    1. `require_authenticated` → 401 если нет токена.
    2. `require_access_level(STAFF)` → 403 если scope < staff_support.
    3. `ensure_can_write_access_level(target, levels)` → 403 если writer
       пытается создать статью с access_level, к которому сам не имеет
       доступа (ADR-0003 write-extension).

    Idempotency-Key (E5.1 #44): если header `Idempotency-Key: <UUID>` есть
    в request — `process_idempotency_key` либо replay'ит cached response
    (если retry с тем же body), либо 409 (retry с другим body), либо
    готовит save-callback для cache'ирования после execution.

    Audit log: после успешного commit'а — `articles.created` с метаданными
    (БЕЗ body_markdown/title — ФЗ-152). Best-effort на E4.1; E4.x будет
    писать audit в той же транзакции через DB-таблицу.
    """
    # E5.1: если idempotency replay есть — возвращаем cached response.
    # `JSONResponse` напрямую — bypass'ит `response_model=ArticleResponse`
    # валидацию (cached body может быть от старого schema; trust cache).
    if idempotency.replay is not None:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=idempotency.replay.status,
            content=idempotency.replay.body,
            headers=idempotency.replay.headers,
        )

    await _ensure_write_target_or_report_bypass(
        target=payload.access_level,
        access_levels=access_levels,
        actor_sub=claims["sub"],
        slug=payload.slug,
        method="POST",
        dispatcher=webhook_dispatcher,
    )

    article = await repo.create(payload, actor_sub=claims["sub"])

    # NB: audit log пишется в отдельную транзакцию ПОСЛЕ commit'а article'а
    # (article repo commit'ит внутри). Crash window между commit'ами ещё
    # существует — strict outbox требует repo refactor (отдельный backlog).
    # Legacy stdout logger.info оставляем для дебага/grep'а.
    log_article_created(
        actor_sub=claims["sub"],
        slug=article.slug,
        access_level=article.access_level,
    )
    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_ARTICLES_CREATED,
        resource_type=RESOURCE_ARTICLE,
        resource_id=article.slug,
        metadata={"access_level": article.access_level},
    )

    # E5.3 #91: fire webhook event если создаём сразу PUBLISHED.
    await _maybe_dispatch_article_status_event(webhook_dispatcher, article, old_status=None)
    # ADR-0010 #130: RAG indexer (gated на RAG_ENABLED).
    await _maybe_index_article(indexer, article)

    location = f"/api/v1/articles/{article.slug}"
    response.headers["Location"] = location

    article_response = ArticleResponse.model_validate(article)

    # E5.1: cache response для retry-safety (если key передан).
    # Save вызывается ТОЛЬКО на success path — 4xx/5xx exception bypass'ит
    # save → fresh evaluation на retry (Stripe pattern).
    await idempotency.save(
        status_code=status.HTTP_201_CREATED,
        body=article_response.model_dump(mode="json"),
        headers={"Location": location},
    )

    return article_response


@router.put(
    "/{slug}",
    response_model=ArticleResponse,
    summary="Полностью заменить статью (требует scope ≥ staff_support)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope или target access_level недоступен"},
        404: {"description": "Статья не существует или недоступна (ADR-0003 mask)"},
        412: {"description": "If-Match не совпадает с current ETag (E5.2)"},
        422: {"description": "Невалидный payload или slug-mismatch"},
    },
)
async def replace_article(
    payload: ArticleInput,
    slug: str = Path(
        ...,
        min_length=1,
        max_length=200,
        pattern=SLUG_PATTERN,
        description="Канонический идентификатор статьи (ADR-0006)",
    ),
    if_match: str | None = Header(default=None, alias="If-Match"),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: ArticleRepository = Depends(get_article_repository),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    indexer: IndexerService = Depends(get_indexer_service),
) -> ArticleResponse:
    """Полностью заменяет статью.

    Авторизация (двух-уровневая, ADR-0003 источник + цель):
    1. `require_authenticated` → 401 без токена.
    2. `require_access_level(STAFF)` → 403 если scope < staff_support.
    3. **Source check** (в `repo.update`): writer не видит исходник → 404.
    4. **Target check**: `ensure_can_write_access_level(target, levels)` →
       403 если writer пытается установить недоступный target.

    Slug change через PUT запрещён: `payload.slug` должен совпадать с
    `path.slug` (или 422). Переименование — через DELETE+POST.

    Audit: метаданные старых/новых access_level и status; БЕЗ content
    (ФЗ-152). Best-effort после commit (E4.x DB audit_log → at-least-once).
    """
    if payload.slug != slug:
        # 422 — FastAPI/Starlette deprecate `HTTP_422_UNPROCESSABLE_ENTITY` в
        # пользу `HTTP_422_UNPROCESSABLE_CONTENT`; используем код-литерал для
        # совместимости с разными версиями Starlette до выравнивания в E5.
        raise HTTPException(
            status_code=422,
            detail=("Slug in path and body must match; renaming is not supported in PUT"),
        )

    # Target check (ADR-0003 Level-2) — ДО source check, чтобы 403 не
    # утекал информацию о существовании. Если 403 — клиент знает только,
    # что target ему недоступен; источник статьи остаётся опаковым.
    await _ensure_write_target_or_report_bypass(
        target=payload.access_level,
        access_levels=access_levels,
        actor_sub=claims["sub"],
        slug=slug,
        method="PUT",
        dispatcher=webhook_dispatcher,
    )

    updated = await repo.update(
        slug,
        payload,
        access_levels,
        actor_sub=claims["sub"],
        if_match=if_match,
    )
    if updated is None:
        # Source check (ADR-0003 mask): нет статьи ИЛИ scope её не видит.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )

    article, old_access_level, old_status = updated
    log_article_updated(
        actor_sub=claims["sub"],
        slug=article.slug,
        old_access_level=old_access_level,
        new_access_level=article.access_level,
        old_status=old_status,
        new_status=article.status,
    )
    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_ARTICLES_UPDATED,
        resource_type=RESOURCE_ARTICLE,
        resource_id=article.slug,
        metadata={
            "old_access_level": old_access_level,
            "new_access_level": article.access_level,
            "old_status": old_status,
            "new_status": article.status,
            "via": "PUT",
        },
    )
    # E5.3 #91: fire matching webhook event на status-перехода.
    await _maybe_dispatch_article_status_event(webhook_dispatcher, article, old_status=old_status)
    # #221 / ТЗ §5.1: fire `article.updated` для любого PUT (PUT replaces
    # body полностью — listим `full_replacement` вместо ложного field-list'а).
    await _dispatch_article_updated(
        webhook_dispatcher, article, changed_fields=["full_replacement"]
    )
    # ADR-0010 #130: RAG indexer.
    await _maybe_index_article(indexer, article)
    return ArticleResponse.model_validate(article)


@router.delete(
    "/{slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Архивировать статью (soft delete, требует scope ≥ staff_support)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        404: {"description": "Статья не существует или недоступна (ADR-0003 mask)"},
    },
)
async def archive_article(
    slug: str = Path(
        ...,
        min_length=1,
        max_length=200,
        pattern=SLUG_PATTERN,
        description="Канонический идентификатор статьи (ADR-0006)",
    ),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: ArticleRepository = Depends(get_article_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    indexer: IndexerService = Depends(get_indexer_service),
) -> Response:
    """Soft-delete: переводит статью в `status='ARCHIVED'` (не удаляет из БД).

    Авторизация (ADR-0003 source-only):
    1. `require_authenticated` → 401.
    2. `require_access_level(STAFF)` → 403.
    3. Source check (в `repo.archive`): writer не видит источник → 404.

    Target Level-2 (access_level) НЕ применяется: DELETE меняет `status`,
    не `access_level`.

    Идемпотентность: DELETE на уже-ARCHIVED → 204 без мутации (per RFC 7231).
    Audit пишется с `was_status='ARCHIVED'` — сигнал повторной DELETE.
    """
    result = await repo.archive(slug, access_levels, actor_sub=claims["sub"])
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )
    was_status, was_access_level = result
    log_article_archived(
        actor_sub=claims["sub"],
        slug=slug,
        was_status=was_status,
        was_access_level=was_access_level,
    )
    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_ARTICLES_ARCHIVED,
        resource_type=RESOURCE_ARTICLE,
        resource_id=slug,
        metadata={
            "was_status": was_status,
            "was_access_level": was_access_level,
        },
    )
    # ADR-0010 #130: RAG indexer — archive means article больше не
    # retrieve'ится. Slug-based variant (id не доступен в archive handler'е).
    await _maybe_remove_article_by_slug(indexer, slug)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{slug}/history",
    summary="История изменений статьи",
    responses={
        200: {"description": "История версий"},
        304: {"description": "Не изменилась с last ETag"},
        404: {"description": "Статья не существует или недоступна (ADR-0003 mask)"},
    },
)
async def get_article_history(
    response: Response,
    slug: str = Path(
        ...,
        min_length=1,
        max_length=200,
        pattern=SLUG_PATTERN,
        description="Канонический идентификатор статьи (ADR-0006)",
    ),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ArticleRepository = Depends(get_article_repository),
) -> Any:
    """История версий статьи в порядке `version DESC`.

    Visibility наследуется от parent article (ADR-0003 source-mask):
    `repo.list_versions` сначала вызывает `get_by_slug`, и если scope не
    видит article → None → 404. Это значит, что history non-PUBLISHED
    статьи скрыта (даже для writer'а) — endpoint следует публичному read
    инварианту. Editor-history (`/staff/.../history`) — отдельный endpoint
    в будущем (E4.x).

    E5.2: ETag (от max version) + `If-None-Match` → 304.
    `Vary: Authorization` — shared-proxy safety.
    """
    if not access_levels:
        # Defence-in-depth (как в `GET /articles/{slug}`).
        raise UnauthorizedError(detail="No access levels resolved")

    versions = await repo.list_versions(slug, access_levels)
    if versions is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )

    # E5.2: ETag computes ПОСЛЕ source check (не leak visibility).
    etag = compute_history_etag(versions)
    if if_none_match is not None and if_none_match == etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED,
            headers={"ETag": etag, **DEFAULT_CACHE_HEADERS},
        )

    response.headers["ETag"] = etag
    for k, v in DEFAULT_CACHE_HEADERS.items():
        response.headers[k] = v

    # Мапим `author_sub → author` явно для соответствия OpenAPI.
    return ArticleHistoryResponse(
        data=[
            ArticleVersionResponse(
                version=v.version,
                author=v.author_sub,
                changed_at=v.changed_at,
                event=v.event,
                changes_summary=v.changes_summary,
            )
            for v in versions
        ]
    )


@router.patch(
    "/{slug}",
    response_model=ArticleResponse,
    summary="Частично обновить статью (требует scope ≥ staff_support)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope"},
        404: {"description": "Статья не существует или недоступна (ADR-0003 mask)"},
        422: {"description": "Невалидный payload или попытка изменить access_level/slug"},
    },
)
async def patch_article(
    payload: ArticlePatch,
    slug: str = Path(
        ...,
        min_length=1,
        max_length=200,
        pattern=SLUG_PATTERN,
        description="Канонический идентификатор статьи (ADR-0006)",
    ),
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: ArticleRepository = Depends(get_article_repository),
    webhook_dispatcher: WebhookEventDispatcher = Depends(get_webhook_event_dispatcher),
    audit_repo: AuditRepository = Depends(get_audit_repository),
    indexer: IndexerService = Depends(get_indexer_service),
) -> ArticleResponse:
    """Partial-update: меняет только переданные поля.

    Доступные поля (см. `ArticlePatch`): title, body_markdown, tags, status.
    Запрещённые (через `extra='forbid'`): access_level, slug, category,
    audience, language, short_answer. Их изменение требует PUT (с явным
    target-check для access_level).

    Авторизация (ADR-0003 source-only — без Level-2):
    1. `require_authenticated` → 401.
    2. `require_access_level(STAFF)` → 403.
    3. Source-mask в `repo.patch`: writer не видит источник → 404.

    Empty payload `{}` → 200, no-op (НЕ создаёт версию, идемпотентно).
    """
    result = await repo.patch(slug, payload, access_levels, actor_sub=claims["sub"])
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found",
        )
    article, old_access_level, old_status = result
    log_article_updated(
        actor_sub=claims["sub"],
        slug=article.slug,
        old_access_level=old_access_level,
        new_access_level=article.access_level,
        old_status=old_status,
        new_status=article.status,
    )
    await audit_repo.record(
        actor_sub=claims["sub"],
        action=ACTION_ARTICLES_UPDATED,
        resource_type=RESOURCE_ARTICLE,
        resource_id=article.slug,
        metadata={
            "old_access_level": old_access_level,
            "new_access_level": article.access_level,
            "old_status": old_status,
            "new_status": article.status,
            "via": "PATCH",
        },
    )
    # E5.3 #91: fire matching webhook event на status-перехода.
    await _maybe_dispatch_article_status_event(webhook_dispatcher, article, old_status=old_status)
    # #221 / ТЗ §5.1: fire `article.updated` с granular changed_fields.
    changed_fields = sorted(payload.model_dump(exclude_unset=True).keys())
    await _dispatch_article_updated(webhook_dispatcher, article, changed_fields=changed_fields)
    await _maybe_index_article(indexer, article)
    return ArticleResponse.model_validate(article)


@router.post(
    "/search",
    response_model=ArticlesSearchResponse,
    summary="Полнотекстовый поиск по статьям (Postgres FTS, E2.5a)",
    responses={
        400: {"description": "Невалидный cursor"},
        422: {"description": "Невалидный body (q empty/too long, limit out of range)"},
    },
)
async def search_articles(
    payload: SearchInput,
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ArticleRepository = Depends(get_article_repository),
) -> ArticlesSearchResponse:
    """Search через `websearch_to_tsquery('russian', q)` + GIN index.

    ADR-0003 inherit: `status='PUBLISHED'` + `access_level IN (...)` фильтр
    на SQL — anonymous видит только PUBLIC PUBLISHED статьи.

    Cursor валиден только для стабильного `q` — rank query-dependent.
    """
    if not access_levels:
        # Defence-in-depth (как в `GET /articles/{slug}`).
        raise UnauthorizedError(detail="No access levels resolved")

    # Whitespace-only q → 422 (Pydantic min_length=1 уже ловит "", но не "   ").
    if not payload.q.strip():
        raise HTTPException(
            status_code=422,
            detail="q must not be whitespace-only",
        )

    decoded_cursor = decode_score_cursor(payload.cursor) if payload.cursor else None

    rows, has_more = await repo.search(
        payload.q,
        access_levels,
        cursor=decoded_cursor,
        limit=payload.limit,
    )

    hits = [
        SearchHit(
            id=row_id,
            title=title,
            snippet=snippet,
            # Clip к 1.0 — OpenAPI говорит 0..1; ts_rank теоретически > 1
            # на длинных query c повторяющимися словами.
            score=min(score, 1.0),
        )
        for row_id, title, snippet, score in rows
    ]

    cursor_next: str | None = None
    if rows and has_more:
        last_id, _, _, last_score = rows[-1]
        cursor_next = encode_score_cursor(last_score, last_id)

    return ArticlesSearchResponse(
        data=hits,
        pagination=PaginationInfo(cursor_next=cursor_next, has_more=has_more),
    )
