"""ArticleRepository — единственная точка доступа к таблице articles.

КРИТИЧЕСКИЙ ИНВАРИАНТ ADR-0003: ВСЕ запросы к articles фильтруются по
`access_level IN (...)` на уровне SQL, не на уровне Python.

Repository обязателен (см. ADR-0008 «Repository pattern обязателен»):
router'ы не имеют права работать напрямую с AsyncSession. Это защита
от обхода фильтрации в обход type-system.
"""

from datetime import datetime
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import literal, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.models import Article
from src.api.articles.schemas import ArticleInput
from src.api.auth.scope import AccessLevel
from src.api.db import get_session


class SlugConflictError(HTTPException):
    """HTTP 409 — статья с таким slug уже существует."""

    def __init__(self, slug: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Article with slug '{slug}' already exists",
        )


class ArticleRepository:
    """Read-only репозиторий статей.

    Write-операции (POST/PUT/PATCH/DELETE) появятся в E4 как отдельные
    методы; на E2.1 — только чтение.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_slug(
        self,
        slug: str,
        access_levels: frozenset[AccessLevel],
    ) -> Article | None:
        """Получить опубликованную статью по slug.

        Фильтрация:
        - `slug = :slug` — точное совпадение
        - `status = 'PUBLISHED'` — DRAFT/ARCHIVED невидимы
        - `access_level IN (:allowed_levels)` — ADR-0003 storage-level

        Если для текущего scope нет ни одного подходящего level
        (например, frozenset пустой) — фильтр `IN ()` вернёт 0 строк
        автоматически, мы возвращаем None → router отдаёт 404.

        Возвращает None если статья не существует ИЛИ scope не видит её
        (см. ADR-0003 «404 вместо 403» — маскировка существования).
        """
        allowed_strings = [level.value for level in access_levels]
        stmt = (
            select(Article)
            .where(
                Article.slug == slug,
                Article.status == "PUBLISHED",
                Article.access_level.in_(allowed_strings),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_filtered(
        self,
        access_levels: frozenset[AccessLevel],
        *,
        category: str | None = None,
        audience: str | None = None,
        language: str | None = None,
        cursor: tuple[datetime, UUID] | None = None,
        limit: int = 20,
    ) -> tuple[list[Article], bool]:
        """Возвращает страницу опубликованных статей + флаг `has_more`.

        Фильтрация (всегда):
        - `status = 'PUBLISHED'` — DRAFT/ARCHIVED скрыты на SQL-уровне.
        - `access_level IN (:allowed)` — ADR-0003 critical invariant.

        Опциональные фильтры: `category`, `audience`, `language` (если None
        — не добавляем условие, не используем `OR ... IS NULL`).

        Пагинация — keyset по композитному ключу `(updated_at DESC, id DESC)`.
        Если `cursor` задан, добавляется row-value предикат
        `(updated_at, id) < (:c_u, :c_i)` через `sqlalchemy.tuple_` — это
        row-value comparison, НЕ `AND` (последнее ломает keyset).

        Concurrent INSERT: новые статьи с `updated_at > last_returned` просто
        попадут на следующую страницу. Дубликатов/пропусков нет, потому что
        sort key стабилен и cursor хранит точную нижнюю границу.

        Возвращает `(rows, has_more)`. Запрашиваем `limit + 1` строк: если
        получили больше limit — есть следующая страница, `cursor_next` строит
        router из последнего элемента `rows[:limit]`.
        """
        allowed_strings = [level.value for level in access_levels]
        stmt = select(Article).where(
            Article.status == "PUBLISHED",
            Article.access_level.in_(allowed_strings),
        )
        if category is not None:
            stmt = stmt.where(Article.category == category)
        if audience is not None:
            stmt = stmt.where(Article.audience == audience)
        if language is not None:
            stmt = stmt.where(Article.language == language)
        if cursor is not None:
            cursor_updated_at, cursor_id = cursor
            # `literal(...)` оборачивает Python-значения в ColumnElement —
            # type-system'но корректно, и сохраняет row-value comparison
            # `(a, b) < (x, y)` вместо разворачивания в AND.
            stmt = stmt.where(
                tuple_(Article.updated_at, Article.id)
                < tuple_(literal(cursor_updated_at), literal(cursor_id))
            )
        stmt = stmt.order_by(Article.updated_at.desc(), Article.id.desc()).limit(limit + 1)
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def create(self, payload: ArticleInput) -> Article:
        """Создаёт статью из валидированного payload'а.

        Pydantic уже проверил schema (slug pattern, length, required, enum
        для access_level). Здесь — только DB-уровень: unique slug.

        IntegrityError → 409 SlugConflictError. Другие IntegrityError
        (CHECK constraints на audience/status) теоретически возможны если
        Pydantic пропустит (audience пока str без enum-валидации); тогда
        они уходят в 500 — это документировано в плане как risk до E4.x
        rollout'а enum-валидации на все поля.

        Commit здесь, не в endpoint: один insert = один commit; FastAPI
        `get_session` использует `async with`, без явного commit изменения
        откатятся. Нам нужен commit для возврата ID/created_at server-defaults.
        """
        # `access_level` — AccessLevel enum (StrEnum); .value даёт строку
        # для записи в БД (колонка String, см. models.py).
        article = Article(
            slug=payload.slug,
            title=payload.title,
            body_markdown=payload.body_markdown,
            category=payload.category,
            audience=payload.audience,
            access_level=payload.access_level.value,
            status=payload.status,
            language=payload.language,
            tags=list(payload.tags),
        )
        self._session.add(article)
        try:
            await self._session.flush()
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            # Конкретный код constraint у asyncpg / unique violation.
            # Проверяем по тексту message — фильтруем именно slug-conflict;
            # остальные IntegrityError (CHECK) пробрасываем как есть → 500.
            if "uq_articles_slug" in str(exc.orig) or "articles_slug_key" in str(exc.orig):
                raise SlugConflictError(payload.slug) from exc
            raise
        await self._session.refresh(article)
        return article

    async def update(
        self,
        slug: str,
        payload: ArticleInput,
        access_levels: frozenset[AccessLevel],
    ) -> tuple[Article, str, str] | None:
        """Обновляет статью по slug; возвращает `(article, old_al, old_st)` или None.

        Авторизация (ADR-0003 source-side):
        - `access_level IN (current_levels)` — writer не видит чужие
          статьи → возвращаем None → router 404 (маскировка существования).
        - **НЕ фильтруем `status='PUBLISHED'`**: writer должен видеть свои
          DRAFT/ARCHIVED статьи для редактирования. Это намеренное
          отличие от `get_by_slug`. Read-эндпоинт без auth скрывает
          DRAFT через статусный фильтр; PUT с `require_access_level(STAFF)`
          снимает его — writer уже доверенный.

        Авторизация target-side (Level-2 ADR-0003) — обязанность router'а
        через `ensure_can_write_access_level(payload.access_level, levels)`,
        ДО вызова этого метода. Иначе кто-то может через repo напрямую
        повысить visibility за пределы своего scope.

        Возвращаемый tuple: новый Article + старые access_level/status
        для audit-log дельты (см. `log_article_updated`).

        IntegrityError handling: consistent с `create` (E4.1) — unknown
        IntegrityError (CHECK violations) пробрасываются → 500. Pydantic
        валидация защищает от слов нарушения; backlog #28 для полного
        enum-rollout, до тех пор это знаемый risk.
        """
        allowed_strings = [level.value for level in access_levels]
        stmt = select(Article).where(
            Article.slug == slug,
            Article.access_level.in_(allowed_strings),
        )
        result = await self._session.execute(stmt)
        article = result.scalar_one_or_none()
        if article is None:
            return None

        old_access_level = article.access_level
        old_status = article.status

        # In-place mutation: SQLAlchemy unit-of-work зафиксирует через commit.
        # slug НЕ обновляется (path = identifier, router отвергает mismatch 422).
        article.title = payload.title
        article.body_markdown = payload.body_markdown
        article.category = payload.category
        article.audience = payload.audience
        article.access_level = payload.access_level.value
        article.status = payload.status
        article.language = payload.language
        article.tags = list(payload.tags)

        await self._session.commit()
        await self._session.refresh(article)
        return article, old_access_level, old_status

    async def archive(
        self,
        slug: str,
        access_levels: frozenset[AccessLevel],
    ) -> tuple[str, str] | None:
        """Soft-delete: status → 'ARCHIVED'. Возвращает `(was_status,
        was_access_level)` или None если статья не найдена / scope не видит.

        Авторизация (ADR-0003 source-side, как `update`):
        - `access_level IN (current_levels)` — writer не видит чужую → None
          → router 404 (маскировка).
        - **НЕ фильтруем `status='PUBLISHED'`** — writer может архивировать
          DRAFT/уже-ARCHIVED статью (идемпотентность DELETE per RFC 7231).

        Target Level-2 check (`access_level` change) НЕ требуется: DELETE
        меняет `status`, не `access_level`. Writer прошёл source check —
        этого достаточно.

        **Идемпотентность с no-op для already-ARCHIVED** (per Reviewer N3):
        если статья уже `ARCHIVED`, мы НЕ мутируем `status` — это значит
        `updated_at` не обновится (нет UPDATE SQL). 204 всё равно
        возвращается per RFC 7231. Audit-log пишется с `was_status=
        'ARCHIVED'` — сигнал повторной DELETE для алертинга.
        """
        allowed_strings = [level.value for level in access_levels]
        stmt = select(Article).where(
            Article.slug == slug,
            Article.access_level.in_(allowed_strings),
        )
        result = await self._session.execute(stmt)
        article = result.scalar_one_or_none()
        if article is None:
            return None

        was_status = article.status
        was_access_level = article.access_level

        if was_status != "ARCHIVED":
            # Мутируем только если ещё не архивирована — иначе no-op для
            # сохранения `updated_at` (idempotent without side effects).
            article.status = "ARCHIVED"
            await self._session.commit()

        return was_status, was_access_level


def get_article_repository(
    session: AsyncSession = Depends(get_session),
) -> ArticleRepository:
    """FastAPI Depends-factory для ArticleRepository.

    Router'ы используют ИМЕННО эту dependency, не `get_session` напрямую —
    так инвариант ADR-0008 «router не работает с AsyncSession» защищён
    type-system'ом: signature endpoint'а не содержит AsyncSession.
    """
    return ArticleRepository(session)
