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
