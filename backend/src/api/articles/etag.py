"""HTTP ETag helpers для conditional GET и optimistic concurrency (E5.2 #48).

ETag формат — **weak** (RFC 7232 §2.1): `W/"<sha256[0:16]>"`. Semantic
equivalence — достаточно для нашей семантики (JSON encoding может
отличаться по whitespace между ответами, но state одинаков).

Hash включает:
- `id` — unique per article.
- `updated_at` — server-set, меняется на каждый write (`onupdate=func.now()`).
- `access_level` — visibility change → cache invalidate.
- `status` — DRAFT/PUBLISHED/ARCHIVED transition → cache invalidate.

**ETag НЕ leak visibility info**: same algorithm для всех scopes — anonymous
и staff_admin получают same ETag для same article state. Anonymous узнаёт
лишь что article в этом state существует (что он уже знает из 200 response).

**Race protection (ETag-check vs UPDATE)**: E5.0 advisory lock сериализует
concurrent writes. Order в `repo.update`:
1. acquire_lock (E5.0).
2. SELECT (source check).
3. compute current ETag.
4. compare с If-Match → 412.
5. mutate + commit (lock released).
"""

from hashlib import sha256

from src.api.articles.models import Article, ArticleVersion


def compute_article_etag(article: Article) -> str:
    """Weak ETag для GET /articles/{slug} и If-Match сверки.

    Формат: `W/"<16 hex chars>"`. 16 chars = 8 bytes = 2^64 entropy,
    collision negligible для article scale.
    """
    payload = (
        f"{article.id}|{article.updated_at.isoformat()}|" f"{article.access_level}|{article.status}"
    )
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f'W/"{digest}"'


def compute_history_etag(versions: list[ArticleVersion]) -> str:
    """Weak ETag для GET /articles/{slug}/history.

    Базируется на максимальной версии (DESC order — `versions[0]`).
    Пустой список (article без версий — non-normal flow) → `W/"empty"`.
    """
    if not versions:
        return 'W/"empty"'
    latest = versions[0]  # repo возвращает DESC order
    payload = f"{latest.article_id}|{latest.version}|{latest.changed_at.isoformat()}"
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f'W/"{digest}"'


# Cache headers per OpenAPI spec + B1 plan-review (Vary: Authorization для
# shared proxy safety per RFC 7234 §4.1).
DEFAULT_CACHE_HEADERS: dict[str, str] = {
    "Cache-Control": "public, max-age=60",
    "Vary": "Authorization",
}
