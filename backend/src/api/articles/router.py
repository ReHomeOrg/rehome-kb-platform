"""FastAPI router для `/api/v1/articles/*`.

E2.1 — только `GET /articles/{slug}`. Дальнейшие операции (list, поиск,
write) добавляются в следующих эпиках через дополнительные методы router.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from src.api.articles.audit import (
    log_article_archived,
    log_article_created,
    log_article_updated,
)
from src.api.articles.authorization import ensure_can_write_access_level
from src.api.articles.cursor import decode_cursor, encode_cursor
from src.api.articles.repository import ArticleRepository, get_article_repository
from src.api.articles.schemas import (
    ArticleHistoryResponse,
    ArticleInput,
    ArticleResponse,
    ArticlesListResponse,
    ArticleSummary,
    ArticleVersionResponse,
    PaginationInfo,
)
from src.api.auth.dependency import (
    get_current_access_levels,
    require_access_level,
    require_authenticated,
)
from src.api.auth.exceptions import UnauthorizedError
from src.api.auth.scope import AccessLevel

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
    response_model=ArticleResponse,
    summary="Получить статью по slug",
    responses={
        404: {"description": "Статья не существует или недоступна текущему scope"},
    },
)
async def get_article_by_slug(
    slug: str = Path(
        ...,
        min_length=1,
        max_length=200,
        pattern=SLUG_PATTERN,
        description="Канонический идентификатор статьи (ADR-0006)",
    ),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ArticleRepository = Depends(get_article_repository),
) -> ArticleResponse:
    """Отдаёт опубликованную статью с фильтрацией по access_level.

    ADR-0008: router принимает `ArticleRepository`, не `AsyncSession` —
    storage-level фильтр (ADR-0003) защищён type-system'ом от случайного
    обхода через прямой `session.execute(...)`.

    Маскировка: если статья существует, но scope её не видит, возвращаем 404
    (не 403) — клиент не должен узнавать факт существования закрытого ресурса.
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
) -> ArticleResponse:
    """Создаёт статью.

    Авторизация (двух-уровневая):
    1. `require_authenticated` → 401 если нет токена.
    2. `require_access_level(STAFF)` → 403 если scope < staff_support.
    3. `ensure_can_write_access_level(target, levels)` → 403 если writer
       пытается создать статью с access_level, к которому сам не имеет
       доступа (ADR-0003 write-extension).

    Audit log: после успешного commit'а — `articles.created` с метаданными
    (БЕЗ body_markdown/title — ФЗ-152). Best-effort на E4.1; E4.x будет
    писать audit в той же транзакции через DB-таблицу.
    """
    ensure_can_write_access_level(payload.access_level, access_levels)

    article = await repo.create(payload, actor_sub=claims["sub"])

    # NB: audit log вне транзакции — best-effort на E4.1. Risk
    # документирован в Issue #27 / Plan; mitigation для compliance —
    # E4.x DB-таблица audit_log.
    log_article_created(
        actor_sub=claims["sub"],
        slug=article.slug,
        access_level=article.access_level,
    )

    response.headers["Location"] = f"/api/v1/articles/{article.slug}"
    return ArticleResponse.model_validate(article)


@router.put(
    "/{slug}",
    response_model=ArticleResponse,
    summary="Полностью заменить статью (требует scope ≥ staff_support)",
    responses={
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Недостаточный scope или target access_level недоступен"},
        404: {"description": "Статья не существует или недоступна (ADR-0003 mask)"},
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
    claims: dict[str, Any] = Depends(require_authenticated),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    _staff_required: None = Depends(require_access_level(AccessLevel.STAFF)),
    repo: ArticleRepository = Depends(get_article_repository),
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
    ensure_can_write_access_level(payload.access_level, access_levels)

    updated = await repo.update(slug, payload, access_levels, actor_sub=claims["sub"])
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
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{slug}/history",
    response_model=ArticleHistoryResponse,
    summary="История изменений статьи",
    responses={
        404: {"description": "Статья не существует или недоступна (ADR-0003 mask)"},
    },
)
async def get_article_history(
    slug: str = Path(
        ...,
        min_length=1,
        max_length=200,
        pattern=SLUG_PATTERN,
        description="Канонический идентификатор статьи (ADR-0006)",
    ),
    access_levels: frozenset[AccessLevel] = Depends(get_current_access_levels),
    repo: ArticleRepository = Depends(get_article_repository),
) -> ArticleHistoryResponse:
    """История версий статьи в порядке `version DESC`.

    Visibility наследуется от parent article (ADR-0003 source-mask):
    `repo.list_versions` сначала вызывает `get_by_slug`, и если scope не
    видит article → None → 404. Это значит, что history non-PUBLISHED
    статьи скрыта (даже для writer'а) — endpoint следует публичному read
    инварианту. Editor-history (`/staff/.../history`) — отдельный endpoint
    в будущем (E4.x).
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
