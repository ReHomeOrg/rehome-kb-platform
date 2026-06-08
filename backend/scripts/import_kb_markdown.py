"""Import KB articles from the v5 Markdown package into `/api/v1/articles`.

The v5 package uses blocks like:

    ### Статья 1. ...
    ```yaml
    id: 1
    question: "..."
    category: 1_start
    audience: [tenant, owner]
    access_level: PUBLIC
    tags: [...]
    related: [...]
    ```
    Body...

The API currently stores one `audience` value per article, so multi-role
articles are imported as `all`; `owner` is normalized to `landlord`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

try:
    from transliterate import translit  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover - depends on ops environment
    translit = None

API = "http://localhost:8000/api/v1"
TOKEN_PATH = Path("/tmp/.kb-token")

AUDIENCE_MAP = {
    "all": "all",
    "guest": "guest",
    "tenant": "tenant",
    "owner": "landlord",
    "landlord": "landlord",
    "agent": "agent",
    "staff": "staff",
}
ACCESS_MAP = {"PUBLIC", "LOGGED", "AGENT", "STAFF", "LEGAL", "HR_RESTRICTED"}

ARTICLE_RE = re.compile(
    r"^### Статья\s+(?P<num>\d+)\.\s+(?P<headline>.+?)\n"
    r"```yaml\n(?P<meta>.*?)\n```\n"
    r"(?P<body>.*?)(?=\n### (?:Статья|Категория)|\n## |\Z)",
    flags=re.MULTILINE | re.DOTALL,
)
CATEGORY_RE = re.compile(
    r"^### Категория\s+(?P<slug>[^\s—]+)\s+—\s+(?P<title>.+?)\s*$",
    flags=re.MULTILINE,
)


def to_slug(title: str, *, fallback: str, max_len: int = 80) -> str:
    """Cyrillic title -> kebab-case latin slug."""
    if translit is not None:
        try:
            s = translit(title, "ru", reversed=True)
        except Exception:
            s = title
    else:
        s = title
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len].rstrip("-") or fallback


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_scalar_or_list(raw: str) -> str | list[str] | list[int]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        items: list[str | int] = []
        for chunk in raw[1:-1].split(","):
            item = _strip_quotes(chunk.strip())
            if not item:
                continue
            if item.isdigit():
                items.append(int(item))
            else:
                items.append(item)
        return items
    if raw.isdigit():
        return raw
    return _strip_quotes(raw)


def parse_meta(block: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = _parse_scalar_or_list(value)
    return meta


def normalize_audience(value: Any) -> str:
    values = value if isinstance(value, list) else [value]
    normalized = [AUDIENCE_MAP.get(str(v).strip().lower()) for v in values]
    normalized = [v for v in normalized if v]
    if not normalized:
        return "all"
    unique = list(dict.fromkeys(normalized))
    if "all" in unique or len(unique) > 1:
        return "all"
    return unique[0]


def normalize_tags(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    tags: list[str] = []
    for raw in values:
        tag = str(raw).strip()
        if tag and tag.lower() not in {t.lower() for t in tags}:
            tags.append(tag[:64])
    return tags[:10]


def body_has_open_placeholders(text: str) -> bool:
    """Detect management-decision placeholders like `{support_email}`."""
    return bool(re.search(r"\{[^{}\n]{1,80}\}", text))


def parse_articles(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    articles: list[dict[str, Any]] = []
    slug_by_source_id: dict[str, str] = {}
    used_slugs: set[str] = set()

    matches = list(ARTICLE_RE.finditer(text))
    for match in matches:
        meta = parse_meta(match.group("meta"))
        title = str(meta.get("question") or match.group("headline")).strip()
        if not title:
            continue
        article_id = str(meta.get("id") or match.group("num"))
        base_slug = to_slug(title, fallback=f"article-{article_id}")
        slug = base_slug
        suffix = 1
        while slug in used_slugs:
            suffix += 1
            slug = f"{base_slug}-{suffix}"[:80].rstrip("-")
        used_slugs.add(slug)
        slug_by_source_id[article_id] = slug

    for match in matches:
        meta = parse_meta(match.group("meta"))
        title = str(meta.get("question") or match.group("headline")).strip()
        body = match.group("body").strip()
        if not title or not body:
            continue

        access_level = str(meta.get("access_level") or "PUBLIC").upper()
        if access_level == "INTERNAL":
            access_level = "STAFF"
        if access_level not in ACCESS_MAP:
            access_level = "PUBLIC"

        status = "DRAFT" if body_has_open_placeholders(body) else "PUBLISHED"
        article_id = str(meta.get("id") or match.group("num"))
        slug = slug_by_source_id[article_id]

        related = meta.get("related")
        related_ids = related if isinstance(related, list) else []
        if related_ids:
            links = []
            for item in related_ids:
                related_id = str(item)
                related_slug = slug_by_source_id.get(related_id)
                if related_slug:
                    links.append(
                        f"[Перейти к статье {related_id}](/articles/{related_slug})"
                    )
                else:
                    links.append(f"статья {related_id}")
            related_line = "Связанные статьи: " + ", ".join(links)
            body = f"{body}\n\n---\n{related_line}"

        articles.append(
            {
                "slug": slug,
                "title": title[:200],
                "body_markdown": body,
                "category": str(meta.get("category") or "general")[:100],
                "audience": normalize_audience(meta.get("audience", "all")),
                "access_level": access_level,
                "status": status,
                "language": "ru",
                "tags": normalize_tags(meta.get("tags", [])),
                "_source_id": article_id,
            }
        )

    return articles


def article_slug_by_source_id(path: Path) -> dict[str, str]:
    return {
        str(article["_source_id"]): str(article["slug"])
        for article in parse_articles(path)
    }


def parse_categories(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    categories: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in CATEGORY_RE.finditer(text):
        slug = match.group("slug").strip()[:100]
        title = match.group("title").strip()[:200]
        if not slug or slug in seen:
            continue
        seen.add(slug)
        categories.append(
            {
                "slug": slug,
                "title": title,
                "description": f"Статьи из категории {title}",
            }
        )
    return categories


async def import_direct_db(path: Path) -> int:
    """Upsert articles/categories directly, matching the deployed seeder style."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.api.articles.models import Article
    from src.api.categories.models import Category
    from src.api.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)

    categories = parse_categories(path)
    articles = parse_articles(path)
    created_cats = updated_cats = created_arts = updated_arts = 0

    async with factory() as session:
        existing_categories: dict[str, Category] = {}
        if categories:
            result = await session.execute(
                select(Category).where(Category.slug.in_([c["slug"] for c in categories]))
            )
            existing_categories = {category.slug: category for category in result.scalars()}

        for category in categories:
            existing = existing_categories.get(category["slug"])
            if existing is None:
                session.add(Category(**category))
                created_cats += 1
                continue

            changed = False
            for key in ("title", "description"):
                if getattr(existing, key) != category[key]:
                    setattr(existing, key, category[key])
                    changed = True
            if existing.archived_at is not None:
                existing.archived_at = None
                changed = True
            if changed:
                updated_cats += 1

        existing_articles: dict[str, Article] = {}
        if articles:
            result = await session.execute(
                select(Article).where(Article.slug.in_([a["slug"] for a in articles]))
            )
            existing_articles = {article.slug: article for article in result.scalars()}

        for article in articles:
            payload = {k: v for k, v in article.items() if not k.startswith("_")}
            existing = existing_articles.get(payload["slug"])
            if existing is None:
                session.add(
                    Article(
                        **payload,
                        summary="",
                        published_at=now if payload["status"] == "PUBLISHED" else None,
                    )
                )
                created_arts += 1
                continue

            changed = False
            for key, value in payload.items():
                if getattr(existing, key) != value:
                    setattr(existing, key, value)
                    changed = True
            if existing.status == "PUBLISHED" and existing.published_at is None:
                existing.published_at = now
                changed = True
            if changed:
                existing.updated_at = now
                updated_arts += 1

        await session.commit()

    await engine.dispose()
    published = sum(1 for article in articles if article["status"] == "PUBLISHED")
    drafts = len(articles) - published
    print(
        "OK: "
        f"categories_created={created_cats}, categories_updated={updated_cats}, "
        f"articles_created={created_arts}, articles_updated={updated_arts}, "
        f"articles_total={len(articles)}, published={published}, drafts={drafts}"
    )
    return 0


def auth_headers(token: str, slug: str, payload: dict[str, Any]) -> dict[str, str]:
    digest = hashlib.sha256(
        f"{slug}\n{payload['title']}\n{payload['body_markdown']}".encode("utf-8")
    ).hexdigest()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Idempotency-Key": f"kb-md-import-{slug}-{digest[:16]}",
    }


def post_or_update(
    client: httpx.Client,
    api: str,
    token: str,
    article: dict[str, Any],
    *,
    update_existing: bool,
) -> str:
    payload = {k: v for k, v in article.items() if not k.startswith("_")}
    slug = payload["slug"]
    headers = auth_headers(token, slug, payload)
    resp = client.post(f"{api}/articles", json=payload, headers=headers)
    if resp.status_code == 201:
        return f"OK  {slug}"
    if resp.status_code != 409 or not update_existing:
        return f"ERR {resp.status_code} {slug}: {resp.text[:240]}"

    put_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    put_resp = client.put(f"{api}/articles/{slug}", json=payload, headers=put_headers)
    if put_resp.status_code == 200:
        return f"UPD {slug}"
    return f"ERR {put_resp.status_code} {slug}: {put_resp.text[:240]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("path", type=Path, help="Path to v5 Markdown package")
    parser.add_argument("--api", default=API, help="Base API URL")
    parser.add_argument("--token-file", type=Path, default=TOKEN_PATH)
    parser.add_argument("--token", default="", help="Bearer token; overrides --token-file")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--direct-db",
        action="store_true",
        help="Upsert directly through SQLAlchemy using DATABASE_URL from environment",
    )
    parser.add_argument(
        "--no-update-existing",
        action="store_true",
        help="Do not PUT existing slugs after POST 409",
    )
    args = parser.parse_args()

    articles = parse_articles(args.path)
    published = sum(1 for article in articles if article["status"] == "PUBLISHED")
    drafts = len(articles) - published
    print(f"Parsed articles: {len(articles)} (PUBLISHED={published}, DRAFT={drafts})")
    if articles:
        sample = articles[0]
        print(
            "Sample: "
            f"id={sample['_source_id']} slug={sample['slug']!r} "
            f"audience={sample['audience']!r} category={sample['category']!r}"
        )

    if args.dry_run:
        return 0
    if not articles:
        return 1
    if args.direct_db:
        return asyncio.run(import_direct_db(args.path))

    token = args.token.strip() or args.token_file.read_text(encoding="utf-8").strip()
    ok = updated = fail = 0
    with httpx.Client(timeout=30.0) as client:
        for index, article in enumerate(articles, 1):
            result = post_or_update(
                client,
                args.api.rstrip("/"),
                token,
                article,
                update_existing=not args.no_update_existing,
            )
            if result.startswith("OK"):
                ok += 1
            elif result.startswith("UPD"):
                updated += 1
            else:
                fail += 1
            if index % 10 == 0 or not result.startswith(("OK", "UPD")):
                print(f"  [{index:3d}/{len(articles)}] {result}")
            time.sleep(0.02)

    print(f"\n=== Summary: OK={ok}, UPD={updated}, FAIL={fail} ===")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
