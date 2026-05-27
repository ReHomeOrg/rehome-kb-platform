"""ArticleRepository — единственная точка доступа к таблице articles.

КРИТИЧЕСКИЙ ИНВАРИАНТ ADR-0003: ВСЕ запросы к articles фильтруются по
`access_level IN (...)` на уровне SQL, не на уровне Python.

Repository обязателен (см. ADR-0008 «Repository pattern обязателен»):
router'ы не имеют права работать напрямую с AsyncSession. Это защита
от обхода фильтрации в обход type-system.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import cast, func, literal, select, text, tuple_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.articles.models import Article, ArticleVersion
from src.api.articles.schemas import ArticleInput, ArticlePatch
from src.api.auth.scope import AccessLevel
from src.api.db import get_session


class SlugConflictError(HTTPException):
    """HTTP 409 — статья с таким slug уже существует."""

    def __init__(self, slug: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Article with slug '{slug}' already exists",
        )


class PreconditionFailedError(HTTPException):
    """HTTP 412 — If-Match не совпадает с current ETag (E5.2 #48).

    Detail без leakage current ETag — client может узнать stale-status,
    но не точное значение (защита от timing-based ETag enumeration).
    """

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Precondition failed: resource has been modified",
        )


class ArticleRepository:
    """Репозиторий статей: read + write операции с ADR-0003 фильтром.

    Read:
    - `get_by_slug` (E2.1) — single article + storage-level filter.
    - `list_filtered` (E2.2) — keyset-пагинация + filters.

    Write (все с двух-уровневой авторизацией: source 404-mask на SQL +
    target Level-2 в router там, где применимо):
    - `create` (E4.1) — POST.
    - `update` (E4.3) — PUT full-replace.
    - `archive` (E4.4) — DELETE → status='ARCHIVED' (soft-delete).

    PATCH partial и article_versions history — будущие эпики.
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
        tags: list[str] | None = None,
        cursor: tuple[datetime, UUID] | None = None,
        limit: int = 20,
    ) -> tuple[list[Article], bool]:
        """Возвращает страницу опубликованных статей + флаг `has_more`.

        Фильтрация (всегда):
        - `status = 'PUBLISHED'` — DRAFT/ARCHIVED скрыты на SQL-уровне.
        - `access_level IN (:allowed)` — ADR-0003 critical invariant.

        Опциональные фильтры: `category`, `audience`, `language`, `tags`
        (если None / пустой list — не добавляем условие).

        `tags` — JSONB AND-semantics: статья должна содержать ВСЕ
        переданные теги (`tags @> ARRAY[...]::jsonb`). GIN-индекс
        `ix_articles_tags_gin` ускоряет containment-запросы. Tags
        нормализуются в lowercase на input boundary (Pydantic validator
        + router `_parse_tags` + migration 0029); SQL match case-sensitive
        по нормализованным значениям.

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
        if tags:
            # JSONB `@>` containment — AND-semantics. Параметризуется через
            # bind params (литералы tags не попадают в скомпилированный SQL).
            # GIN-индекс `ix_articles_tags_gin` (jsonb_path_ops) ускоряет.
            stmt = stmt.where(Article.tags.op("@>")(cast(tags, JSONB)))
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

    async def _acquire_slug_lock(self, slug: str) -> None:
        """Advisory transaction lock на hashtext(slug) для serialization writes.

        **Postgres-specific** (SQLite-fallback unit-тесты подменяют session).
        Lock берётся через `pg_advisory_xact_lock` — авто-релиз на commit/
        rollback (включая connection drop). Сериализует concurrent writes
        одной и той же статьи (по slug); НЕ блокирует read.

        Race-fix для E2.3 `_next_version` (#36, #40): без lock'а два
        concurrent PUT того же slug получат одинаковый MAX(version) →
        UNIQUE constraint violation → 500. С lock'ом — второй writer ждёт
        первого, читает свежий MAX, INSERT'ит version+1 normally.

        `hashtext(slug)` — Postgres builtin int4 hash. Collision-risk
        ~1/2^31 — не correctness issue, только slight performance
        degradation при coincidental collision (две разные статьи
        сериализуются как одна).

        Вызывается ПЕРВЫМ в `update/archive/patch` — ДО SELECT article.
        Закрывает TOCTOU window для всей последовательности (SELECT →
        mutate → next_version → INSERT version → commit).
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:slug))").bindparams(slug=slug)
        )

    async def _next_version(self, article_id: UUID) -> int:
        """MAX(version) + 1 для article_id; 1 если версий ещё нет.

        Race protection: `_acquire_slug_lock(slug)` берётся в write-методах
        ДО этого вызова — concurrent writers того же slug сериализуются,
        UNIQUE (article_id, version) violation не возникает.
        """
        stmt = select(func.max(ArticleVersion.version)).where(
            ArticleVersion.article_id == article_id
        )
        result = await self._session.execute(stmt)
        current_max: int | None = result.scalar()
        return (current_max or 0) + 1

    def _build_version(
        self,
        *,
        article_id: UUID,
        version: int,
        event: str,
        author_sub: str,
        old_status: str | None,
        new_status: str,
        old_access_level: str | None,
        new_access_level: str,
        summary: str | None,
    ) -> ArticleVersion:
        """Создаёт ArticleVersion-row для добавления в session.

        НЕ commit'ит; вызывающая сторона делает commit в той же транзакции,
        что и article INSERT/UPDATE — atomic.
        """
        return ArticleVersion(
            article_id=article_id,
            version=version,
            event=event,
            author_sub=author_sub,
            old_status=old_status,
            new_status=new_status,
            old_access_level=old_access_level,
            new_access_level=new_access_level,
            changes_summary=summary,
        )

    async def create(self, payload: ArticleInput, *, actor_sub: str) -> Article:
        """Создаёт статью + version-row (version=1, event=CREATE) atomic.

        Pydantic уже проверил schema (включая Literal enums #353).
        IntegrityError по `uq_articles_slug` → 409 SlugConflictError.
        Прочие IntegrityError (e.g. FK на category отсутствует) → 500
        — programmer error, не user input.

        `actor_sub` — Keycloak `sub` claim писателя, для audit (E4.1) и
        version (E2.3). Router передаёт из `claims["sub"]` после
        `require_authenticated`.

        Legacy callers получают commit внутри. ADR-0026 Slice 1 path —
        `create_atomic` (no commit; caller wraps audit + outbox в same
        transaction).
        """
        article = await self.create_atomic(payload, actor_sub=actor_sub)
        await self._session.commit()
        await self._session.refresh(article)
        return article

    async def create_atomic(
        self,
        payload: ArticleInput,
        *,
        actor_sub: str,
    ) -> Article:
        """Same logic as `create` но без commit'а (ADR-0026 Slice 1).

        Caller commit'ит в same transaction вместе с audit row + outbox
        enqueue → atomicity guarantee для ФЗ-152 §22 audit-trail
        completeness invariant.
        """
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
            # flush получает article.id (server-default UUID).
            await self._session.flush()
            # E2.3: version-row в той же транзакции — atomic.
            version_row = self._build_version(
                article_id=article.id,
                version=1,
                event="CREATE",
                author_sub=actor_sub,
                old_status=None,
                new_status=article.status,
                old_access_level=None,
                new_access_level=article.access_level,
                summary="Article created",
            )
            self._session.add(version_row)
            # NB: version_row не flush'ится здесь — caller (session.commit
            # в handler или внутри `create()` для legacy callers) flushes
            # на commit. Это позволяет audit + outbox писать в same session
            # с одним финальным commit per ADR-0026 Slice 1.
        except IntegrityError as exc:
            await self._session.rollback()
            if "uq_articles_slug" in str(exc.orig) or "articles_slug_key" in str(exc.orig):
                raise SlugConflictError(payload.slug) from exc
            raise
        return article

    async def update(
        self,
        slug: str,
        payload: ArticleInput,
        access_levels: frozenset[AccessLevel],
        *,
        actor_sub: str,
        if_match: str | None = None,
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
        IntegrityError пробрасывается → 500. Pydantic Literal enums (#353)
        защищают от bad audience/status/language на input boundary.

        Race protection (E5.0 #40): `_acquire_slug_lock(slug)` берётся
        ПЕРВЫМ — сериализует concurrent writes того же slug.

        Optimistic concurrency (E5.2 #48): `if_match` — opt-in client-side
        check. Если передан и не совпадает с current ETag → 412
        PreconditionFailedError. Check проходит ВНУТРИ advisory lock'а —
        atomic c последующим UPDATE.
        """
        await self._acquire_slug_lock(slug)
        allowed_strings = [level.value for level in access_levels]
        stmt = select(Article).where(
            Article.slug == slug,
            Article.access_level.in_(allowed_strings),
        )
        result = await self._session.execute(stmt)
        article = result.scalar_one_or_none()
        if article is None:
            return None

        # E5.2 optimistic concurrency check (within advisory lock for atomicity).
        if if_match is not None:
            # Lazy import чтобы избежать circular (etag → models → ...).
            from src.api.articles.etag import compute_article_etag

            current_etag = compute_article_etag(article)
            if current_etag != if_match:
                raise PreconditionFailedError

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

        # E2.3: version-row в той же транзакции — atomic с UPDATE article.
        # PUT всегда создаёт версию, даже если payload идентичен текущему
        # состоянию (UPDATE — это акт, не diff; см. plan revision).
        next_v = await self._next_version(article.id)
        version_row = self._build_version(
            article_id=article.id,
            version=next_v,
            event="UPDATE",
            author_sub=actor_sub,
            old_status=old_status,
            new_status=article.status,
            old_access_level=old_access_level,
            new_access_level=article.access_level,
            summary="Updated",
        )
        self._session.add(version_row)
        await self._session.commit()
        await self._session.refresh(article)
        return article, old_access_level, old_status

    async def archive(
        self,
        slug: str,
        access_levels: frozenset[AccessLevel],
        *,
        actor_sub: str,
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

        Race protection (E5.0 #40): `_acquire_slug_lock(slug)` берётся
        ПЕРВЫМ — сериализует concurrent writes того же slug.
        """
        await self._acquire_slug_lock(slug)
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
            # Мутируем только если ещё не архивирована.
            article.status = "ARCHIVED"
            # E2.3: version-row в той же транзакции.
            next_v = await self._next_version(article.id)
            version_row = self._build_version(
                article_id=article.id,
                version=next_v,
                event="ARCHIVE",
                author_sub=actor_sub,
                old_status=was_status,
                new_status="ARCHIVED",
                old_access_level=was_access_level,
                new_access_level=was_access_level,
                summary=f"Archived (was: {was_status})",
            )
            self._session.add(version_row)
            await self._session.commit()
        # else: already-ARCHIVED → no-op, version НЕ создаётся (idempotent).

        return was_status, was_access_level

    async def patch(
        self,
        slug: str,
        payload: ArticlePatch,
        access_levels: frozenset[AccessLevel],
        *,
        actor_sub: str,
    ) -> tuple[Article, str, str] | None:
        """Partial-update: меняет только переданные поля `payload`.

        Авторизация (ADR-0003 source-side, как `update`):
        - `access_level IN (current_levels)` — writer не видит чужие → None → 404.
        - НЕ фильтруем `status='PUBLISHED'` — writer редактирует DRAFT/ARCHIVED.

        Target check (Level-2) НЕ применяется: ArticlePatch не содержит
        `access_level` (security-by-design — смена visibility только через PUT).

        `payload.model_dump(exclude_unset=True)` — только явно переданные поля.
        Empty payload `{}` → no-op (НЕ создаём версию, НЕ commit'им) → 200.

        Atomic с version-row (event='UPDATE', как E4.3 update). `status='ARCHIVED'`
        через PATCH создаёт event=UPDATE (НЕ event=ARCHIVE) — намеренное
        различие с DELETE для семантики history. Для архивации лучше DELETE.

        Race protection (E5.0 #40): `_acquire_slug_lock(slug)` берётся
        ПЕРВЫМ — сериализует concurrent writes того же slug.

        Возвращает `(article, old_access_level, old_status)` или None для router.
        """
        await self._acquire_slug_lock(slug)
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

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            # Empty payload {} — no-op (idempotent). НЕ создаём версию,
            # НЕ вызываем commit — нет реальных изменений.
            return article, old_access_level, old_status

        for field, value in updates.items():
            setattr(article, field, value)

        next_v = await self._next_version(article.id)
        version_row = self._build_version(
            article_id=article.id,
            version=next_v,
            event="UPDATE",
            author_sub=actor_sub,
            old_status=old_status,
            new_status=article.status,
            old_access_level=old_access_level,
            new_access_level=article.access_level,
            summary="Patched",
        )
        self._session.add(version_row)
        await self._session.commit()
        await self._session.refresh(article)
        return article, old_access_level, old_status

    async def list_versions(
        self,
        slug: str,
        access_levels: frozenset[AccessLevel],
    ) -> list[ArticleVersion] | None:
        """Возвращает версии Article в порядке version DESC.

        Visibility наследуется от parent article (ADR-0003 source-mask):
        сначала `get_by_slug(slug, access_levels)` — если None → возвращаем
        None → router 404. Иначе SELECT versions для `article.id`.

        Это значит, что history non-PUBLISHED статьи (DRAFT/ARCHIVED) скрыта
        от всех (даже writer'а) через этот endpoint — он наследует public
        read-инвариант. Editor-history (`/staff/.../history`) — отдельный
        endpoint в будущем (E4.x).

        Список может быть пустой только при non-нормальном flow (статья
        была вставлена напрямую в БД, минуя `create`); в production
        нормально каждая статья имеет минимум version=1.
        """
        article = await self.get_by_slug(slug, access_levels)
        if article is None:
            return None
        stmt = (
            select(ArticleVersion)
            .where(ArticleVersion.article_id == article.id)
            .order_by(ArticleVersion.version.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def search(
        self,
        q: str,
        access_levels: frozenset[AccessLevel],
        *,
        cursor: tuple[float, UUID] | None = None,
        limit: int = 10,
    ) -> tuple[list[tuple[UUID, str, str, str, float]], bool]:
        """Postgres FTS search через `search_vector @@ websearch_to_tsquery`.

        Возвращает `[(id, slug, title, snippet, score), ...]` + `has_more`.
        `slug` нужен для citation URLs в hybrid retrieval (RetrievalService
        RRF fusion).

        Авторизация (ADR-0003 inherit):
        - `status='PUBLISHED'` — read-mask (DRAFT/ARCHIVED скрыты).
        - `access_level IN (current_levels)` — storage-level фильтр.

        Ranking: `ts_rank` от 0 (типично 0..1 на коротких запросах).
        Tie-breaker: `id` DESC (стабильность при одинаковом score).

        Snippet: `ts_headline('russian', body_markdown, q,
        'MaxFragments=1, MaxWords=20')` — фрагмент с `<b>match</b>`.
        **WARNING**: `ts_headline` НЕ escape'нет HTML в body_markdown —
        frontend ОБЯЗАН sanitize перед рендерингом (DOMPurify).

        Cursor: keyset на `(rank, id)` через `tuple_(...)` (E2.2 паттерн).
        Cursor валиден только для стабильного `q` (rank query-dependent).

        Anti-SQL-injection: `q` идёт через `websearch_to_tsquery` bind
        param (Postgres парсит как text query, не SQL). `to_tsquery` —
        unsafe для user input; не используем.
        """
        tsq = func.websearch_to_tsquery("russian", q)
        rank_expr = func.ts_rank(Article.search_vector, tsq).label("score")
        headline = func.ts_headline(
            "russian",
            Article.body_markdown,
            tsq,
            "MaxFragments=1,MaxWords=20",
        ).label("snippet")

        allowed_strings = [level.value for level in access_levels]
        stmt = select(Article.id, Article.slug, Article.title, headline, rank_expr).where(
            Article.status == "PUBLISHED",
            Article.access_level.in_(allowed_strings),
            Article.search_vector.op("@@")(tsq),
        )
        if cursor is not None:
            cur_score, cur_id = cursor
            # Row-value comparison `(rank, id) < (:s, :i)` (E2.2 паттерн).
            stmt = stmt.where(
                tuple_(rank_expr, Article.id) < tuple_(literal(cur_score), literal(cur_id))
            )
        stmt = stmt.order_by(rank_expr.desc(), Article.id.desc()).limit(limit + 1)

        result = await self._session.execute(stmt)
        rows = [(row[0], row[1], row[2], row[3], float(row[4])) for row in result.all()]
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def iter_published_for_reindex(
        self,
        *,
        batch_size: int = 50,
    ) -> AsyncIterator[tuple[UUID, str]]:
        """Async iterator (id, body_markdown) для bulk reindex (#240).

        НЕ применяет access_level фильтр — embeddings индексируют всё
        published, search-time фильтрация всё равно режет по scope.

        Batch'и keyset'ом по `(id ASC)` — простое continue-on-(id > last).
        Memory-bounded: за раз в памяти не более `batch_size` строк.

        Используется `IndexerService.reindex_all_articles` для admin
        reindex endpoint'а (#238). Возвращает только PUBLISHED — ARCHIVED
        embeddings не возрождаются.
        """
        last_id: UUID | None = None
        while True:
            stmt = (
                select(Article.id, Article.body_markdown)
                .where(Article.status == "PUBLISHED")
                .order_by(Article.id)
                .limit(batch_size)
            )
            if last_id is not None:
                stmt = stmt.where(Article.id > last_id)
            result = await self._session.execute(stmt)
            rows = list(result.all())
            if not rows:
                return
            for row_id, body in rows:
                yield (row_id, body)
            last_id = rows[-1][0]
            if len(rows) < batch_size:
                return


def get_article_repository(
    session: AsyncSession = Depends(get_session),
) -> ArticleRepository:
    """FastAPI Depends-factory для ArticleRepository.

    Router'ы используют ИМЕННО эту dependency, не `get_session` напрямую —
    так инвариант ADR-0008 «router не работает с AsyncSession» защищён
    type-system'ом: signature endpoint'а не содержит AsyncSession.
    """
    return ArticleRepository(session)
