"""Audit log для write-операций над статьями.

ФЗ-152: НЕ логируем content (`body_markdown`, `title`, `summary`,
`short_answer`) — только метаданные. Это compliance-первичная привычка,
закладываемая с первого write-эпика.

E4.1 — best-effort через structured logger в stdout. E4.x — DB-таблица
`audit_log` с INSERT в той же транзакции для at-least-once гарантии.
"""

import logging

logger = logging.getLogger("rehome.kb.audit")


def log_article_created(*, actor_sub: str, slug: str, access_level: str) -> None:
    """Структурированный audit-event «articles.created».

    NB: вызывается ПОСЛЕ `await session.commit()` в router'е. Если процесс
    упадёт между commit и log — статья создана, audit-record потерян.
    Это допустимо для E4.1 (минимум, нет compliance trail); E4.x с
    DB-таблицей audit_log решит это через `INSERT INTO audit_log` в той
    же транзакции, что и `INSERT INTO articles`.
    """
    logger.info(
        "articles.created",
        extra={
            "event": "articles.created",
            "actor_sub": actor_sub,
            "slug": slug,
            "access_level": access_level,
        },
    )


def log_article_updated(
    *,
    actor_sub: str,
    slug: str,
    old_access_level: str,
    new_access_level: str,
    old_status: str,
    new_status: str,
) -> None:
    """Структурированный audit-event «articles.updated» с дельтой visibility/state.

    Логируем только дельту по двум audit-значимым полям: access_level
    (видимость статьи) и status (publication state). Контент-дифф
    (title/body/summary/short_answer) НЕ логируется — ФЗ-152 паттерн
    как в `log_article_created` (см. E4.1).

    NB: best-effort после commit'а — same risk as `log_article_created`
    (E4.x с DB-таблицей audit_log закроет at-least-once гарантию).
    """
    logger.info(
        "articles.updated",
        extra={
            "event": "articles.updated",
            "actor_sub": actor_sub,
            "slug": slug,
            "old_access_level": old_access_level,
            "new_access_level": new_access_level,
            "old_status": old_status,
            "new_status": new_status,
        },
    )
