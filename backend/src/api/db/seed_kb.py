"""Self-contained Knowledge Base Seeder (src/api/db/seed_kb.py).

Downloads actual KB and FAQ articles from MinIO, parses them, and inserts them
directly into the Postgres database. Fallbacks to mock seeding on local/dev envs.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from docx import Document
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from transliterate import translit  # type: ignore

from src.api.articles.models import Article
from src.api.categories.models import Category
from src.api.config import get_settings

# ---------------------------------------------------------------------------
# Seed pinning (ADR-0027)

SEED_VERSION = "2026-05-28"
DEFAULT_SEED_BUCKET = "kb-seed"
SEED_PREFIX = f"articles/{SEED_VERSION}"

# Pinned sha256 для текущей seed-версии.
EXPECTED_SHA256: dict[str, str] = {
    "reHome_FAQ_топ15.docx": ("e4d0834db83e12d705176ba65e201fe9bf118eceea80186dcc328bb7d093272b"),
    "reHome_База_статей_120.docx": (
        "3e9db4cb0385c44679fe9687861fd62569bb1f4032ddeee9849137887d3ac05f"
    ),
}

# Маппинг audience значений из .docx → ArticleAudience literal.
AUDIENCE_MAP = {
    "all": "all",
    "guest": "guest",
    "tenant": "tenant",
    "landlord": "landlord",
    "agent": "agent",
    "staff": "staff",
}
ACCESS_MAP = {"PUBLIC", "LOGGED", "AGENT", "STAFF"}

# Slugs of mock articles & categories to delete
MOCK_SLUGS = [
    "kak-zabronirovat-kvartiru",
    "kak-vernut-zalog",
    "chto-takoe-eskrou",
    "kak-projti-verifikaciyu",
    "kak-podpisat-dogovor",
    "kak-rastorgnut-dogovor",
]
MOCK_CAT_SLUGS = ["arenda", "platezhi", "verifikatsiya", "dogovor"]

FALLBACK_CATEGORIES: list[dict[str, str]] = [
    {"slug": "arenda", "title": "Аренда жилья", "description": "Поиск, бронирование и заселение."},
    {
        "slug": "platezhi",
        "title": "Оплата",
        "description": "Оплата проживания и сервисного платежа.",
    },
    {
        "slug": "verifikatsiya",
        "title": "Верификация",
        "description": "Проверка личности и документов.",
    },
    {"slug": "dogovor", "title": "Договор", "description": "Подписание и условия договора найма."},
    {"slug": "support", "title": "Поддержка", "description": "Как связаться с командой reHome."},
]

FALLBACK_ARTICLES: list[dict[str, Any]] = [
    {
        "slug": "kak-zabronirovat-kvartiru",
        "title": "Как забронировать квартиру",
        "category": "arenda",
        "summary": "Пошагово: от выбора квартиры до подтверждения брони.",
        "tags": ["аренда", "бронирование"],
        "body_markdown": (
            "Выберите квартиру в каталоге, откройте карточку объекта и отправьте заявку "
            "на бронирование. После подтверждения можно перейти к договору и оплате."
        ),
    },
    {
        "slug": "kak-platit",
        "title": "Как платить в reHome",
        "category": "platezhi",
        "summary": "Где увидеть сумму к оплате и как провести платеж.",
        "tags": ["оплата", "платежи"],
        "body_markdown": (
            "Сумма и статус оплаты отображаются в карточке сделки. Оплата проводится "
            "через платформу после подтверждения условий и подписания необходимых документов."
        ),
    },
    {
        "slug": "kak-projti-verifikaciyu",
        "title": "Как пройти верификацию",
        "category": "verifikatsiya",
        "summary": "Зачем нужна проверка личности и как она проходит.",
        "tags": ["верификация", "документы"],
        "body_markdown": (
            "Верификация нужна для безопасности сделки. Следуйте шагам в личном кабинете "
            "и загрузите данные, которые запросит платформа."
        ),
    },
    {
        "slug": "kak-podpisat-dogovor",
        "title": "Как подписать договор",
        "category": "dogovor",
        "summary": "Электронное подписание договора найма.",
        "tags": ["договор", "подпись"],
        "body_markdown": (
            "Откройте договор в сделке, проверьте условия и подтвердите подписание. "
            "После подписания обеими сторонами договор становится активным."
        ),
    },
    {
        "slug": "kak-obratitsya-v-podderzhku",
        "title": "Как обратиться в поддержку",
        "category": "support",
        "summary": "Что делать, если в чате не получилось решить вопрос.",
        "tags": ["поддержка", "чат"],
        "body_markdown": (
            "Напишите вопрос в ассистенте поддержки. Если ответа недостаточно, перейдите "
            "в раздел поддержки или создайте обращение, чтобы команда reHome разобрала ситуацию."
        ),
    },
]


# ---------------------------------------------------------------------------
# S3 Fetching


def _fetch_s3(bucket: str, key: str) -> bytes:
    """Получает объект из MinIO (или любого S3-compatible) по env-credentials."""
    from src.api.documents.storage import get_minio_client

    settings = get_settings()
    client = get_minio_client(settings)
    response = client.get_object(bucket_name=bucket, object_name=key)
    try:
        return bytes(response.read())
    finally:
        response.close()
        response.release_conn()


def seed_bucket_name() -> str:
    """Return the object-storage bucket used for pinned seed .docx files."""
    return (
        os.environ.get("KB_SEED_BUCKET")
        or os.environ.get("MINIO_SEED_BUCKET")
        or DEFAULT_SEED_BUCKET
    )


def is_seed_source_unavailable(exc: Exception) -> bool:
    """True only for missing seed bucket/object, not parse/hash/config bugs."""
    text = str(exc)
    return "NoSuchBucket" in text or "NoSuchKey" in text


def fetch_source(uri: str) -> tuple[bytes, str]:
    """Загружает .docx по URI; возвращает (bytes, basename)."""
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()

    if scheme in ("", "file"):
        path = Path(parsed.path if scheme == "file" else uri)
        if not path.is_absolute():
            path = path.resolve()
        return path.read_bytes(), path.name

    if scheme == "seed":
        name = (parsed.netloc + parsed.path).lstrip("/")
        if not name:
            raise ValueError(f"seed:// URI без имени: {uri!r}")
        key = f"{SEED_PREFIX}/{name}"
        return _fetch_s3(seed_bucket_name(), key), name

    if scheme == "s3":
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"s3:// URI должен быть s3://<bucket>/<key>: {uri!r}")
        return _fetch_s3(bucket, key), Path(key).name

    raise ValueError(
        f"Неизвестный URI scheme {scheme!r}; ожидаю file://, s3://, seed://, или абсолютный path"
    )


def verify_sha256(data: bytes, basename: str, *, skip: bool = False) -> None:
    """Проверяет sha256(data) совпадает с pinned значением для basename."""
    actual = hashlib.sha256(data).hexdigest()
    expected = EXPECTED_SHA256.get(basename)
    if skip or expected is None:
        if expected is None:
            print(f"  [sha256] {basename}: {actual} (no pinned hash — skip)")
        else:
            print(f"  [sha256] {basename}: {actual} (skip-verify)")
        return
    if actual != expected:
        raise ValueError(
            f"sha256 mismatch для {basename}:\n  expected: {expected}\n  actual:   {actual}"
        )
    print(f"  [sha256] {basename}: ok")


# ---------------------------------------------------------------------------
# Parsing


def to_slug(title: str, max_len: int = 80) -> str:
    """Cyrillic title → kebab-case latin slug."""
    try:
        s = translit(title, "ru", reversed=True)
    except Exception:
        s = title
    s = s.lower()
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len].rstrip("-") or "untitled"


def parse_tags(line: str) -> list[str]:
    """Парсит `tags: [«a», «b», «c»]` → ['a', 'b', 'c']."""
    line = re.sub(r"^[^:]+:\s*", "", line)
    line = line.strip("[]").strip()
    tags = []
    for chunk in re.split(r"[«»\"',]", line):
        chunk = chunk.strip()
        if chunk and len(chunk) <= 64:
            tags.append(chunk)
    return tags[:10]


def field_value(line: str, key: str) -> str:
    """Вытаскивает `key: value` из `Compact` paragraph."""
    pattern = rf"^{key}\s*:\s*(.*)$"
    m = re.match(pattern, line.strip(), flags=re.IGNORECASE)
    return m.group(1).strip() if m else ""


def parse_faq(data: bytes) -> list[dict[str, Any]]:
    """FAQ doc — каждая статья начинается с Heading 2 'FAQ-NNN'."""
    doc = Document(io.BytesIO(data))
    articles: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    body_lines: list[str] = []

    def flush() -> None:
        if cur is None:
            return
        cur["body_markdown"] = "\n\n".join(body_lines).strip()
        if cur.get("title") and cur["body_markdown"]:
            articles.append(cur)

    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        if p.style and p.style.name == "Heading 2" and text.startswith("FAQ-"):
            flush()
            cur = {
                "category": "FAQ",
                "audience": "all",
                "access_level": "PUBLIC",
                "tags": ["topfaq"],
                "status": "PUBLISHED",
                "language": "ru",
            }
            body_lines = []
            continue
        if cur is None:
            continue
        if v := field_value(text, "question"):
            cur["title"] = v[:200]
            continue
        if v := field_value(text, "category"):
            cur["category"] = v[:100]
            continue
        if v := field_value(text, "audience"):
            cur["audience"] = AUDIENCE_MAP.get(v.lower(), "all")
            continue
        if v := field_value(text, "access_level"):
            v = v.upper()
            cur["access_level"] = v if v in ACCESS_MAP else "PUBLIC"
            continue
        if text.lower().startswith("tags"):
            parsed = parse_tags(text)
            seed = [t for t in cur.get("tags", []) if t not in parsed]
            cur["tags"] = (seed + parsed)[:10]
            continue
        if v := field_value(text, "short_answer"):
            body_lines.append(f"**Кратко:** {v}")
            continue
        if v := field_value(text, "full_answer"):
            body_lines.append(v)
            continue
        body_lines.append(text)
    flush()
    return articles


def parse_kb(data: bytes) -> list[dict[str, Any]]:
    """KB doc — категории как Heading 1, статьи как Heading 2 'Статья N'."""
    doc = Document(io.BytesIO(data))
    articles: list[dict[str, Any]] = []
    current_category = "Общее"
    cur: dict[str, Any] | None = None
    body_lines: list[str] = []

    def flush() -> None:
        if cur is None:
            return
        cur["body_markdown"] = "\n\n".join(body_lines).strip()
        if cur.get("title") and cur["body_markdown"]:
            articles.append(cur)

    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue

        if p.style and p.style.name == "Heading 1" and text.startswith("Категория"):
            cat = re.sub(r"^Категория\s*\d+\.\s*", "", text).strip()
            current_category = cat[:100] or current_category
            flush()
            cur = None
            body_lines = []
            continue

        if p.style and p.style.name == "Heading 2" and text.startswith("Статья"):
            flush()
            cur = {
                "category": current_category,
                "audience": "all",
                "access_level": "PUBLIC",
                "tags": [],
                "status": "PUBLISHED",
                "language": "ru",
            }
            body_lines = []
            continue
        if cur is None:
            continue
        if v := field_value(text, "question"):
            cur["title"] = v[:200]
            continue
        if v := field_value(text, "audience"):
            cur["audience"] = AUDIENCE_MAP.get(v.lower(), "all")
            continue
        if v := field_value(text, "access_level"):
            v = v.upper()
            cur["access_level"] = v if v in ACCESS_MAP else "PUBLIC"
            continue
        if text.lower().startswith("tags"):
            cur["tags"] = parse_tags(text)
            continue
        body_lines.append(text)
    flush()
    return articles


# ---------------------------------------------------------------------------
# Seeding Main Logic


async def count_published_articles(session: Any) -> int:
    result = await session.execute(
        select(func.count()).select_from(Article).where(Article.status == "PUBLISHED")
    )
    return int(result.scalar_one())


async def seed_fallback_public_articles(session: Any, now: datetime) -> tuple[int, int, int]:
    """Emergency public FAQ seed used only when object-storage seed is absent."""
    created_cats = created_arts = skipped = 0

    existing_cats = set((await session.execute(select(Category.slug))).scalars().all())
    for category in FALLBACK_CATEGORIES:
        if category["slug"] in existing_cats:
            continue
        session.add(
            Category(
                slug=category["slug"],
                title=category["title"],
                description=category["description"],
            )
        )
        created_cats += 1
        existing_cats.add(category["slug"])

    existing_arts = set((await session.execute(select(Article.slug))).scalars().all())
    for article in FALLBACK_ARTICLES:
        if article["slug"] in existing_arts:
            skipped += 1
            continue
        session.add(
            Article(
                slug=article["slug"],
                title=article["title"],
                summary=article["summary"],
                body_markdown=article["body_markdown"],
                audience="all",
                language="ru",
                category=article["category"],
                tags=article["tags"],
                access_level="PUBLIC",
                status="PUBLISHED",
                published_at=now,
            )
        )
        created_arts += 1
        existing_arts.add(article["slug"])

    await session.commit()
    return created_cats, created_arts, skipped


async def main() -> int:
    env = os.environ.get("REHOME_ENV", "dev").lower()
    if env in ("prod", "staging"):
        os.environ["MINIO_ENABLED"] = "True"
        print(
            "Prod/Staging environment detected. "
            "Forcing MINIO_ENABLED=True for seeding actual articles."
        )

    settings = get_settings()
    db_url = os.environ.get("DATABASE_URL") or settings.database_url
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    created_cats = created_arts = skipped = 0
    now = datetime.now(UTC)

    try:
        async with factory() as session:
            # 1. Clean up old mock articles & categories in all environments
            from sqlalchemy import delete

            print("Cleaning up old mock data...")
            res_arts = await session.execute(delete(Article).where(Article.slug.in_(MOCK_SLUGS)))
            res_cats = await session.execute(
                delete(Category).where(Category.slug.in_(MOCK_CAT_SLUGS))
            )
            await session.commit()
            print(
                f"Deleted {res_arts.rowcount} mock articles "
                f"and {res_cats.rowcount} mock categories."
            )

            if env in ("prod", "staging"):
                print(f"Running ACTUAL KB seed for environment: {env}")
                try:
                    # 1. Fetch and parse actual articles from S3/MinIO
                    faq_bytes, faq_name = fetch_source("seed://reHome_FAQ_топ15.docx")
                    kb_bytes, kb_name = fetch_source("seed://reHome_База_статей_120.docx")

                    verify_sha256(faq_bytes, faq_name)
                    verify_sha256(kb_bytes, kb_name)

                    faq_articles = parse_faq(faq_bytes)
                    kb_articles = parse_kb(kb_bytes)
                    all_articles = faq_articles + kb_articles

                    # 2. Extract and insert unique categories
                    existing_cats = set(
                        (await session.execute(select(Category.slug))).scalars().all()
                    )
                    unique_categories = {a["category"] for a in all_articles if a.get("category")}
                    for cat_name in unique_categories:
                        if cat_name in existing_cats:
                            continue
                        session.add(
                            Category(
                                slug=cat_name,
                                title=cat_name,
                                description=f"Статьи из категории {cat_name}",
                            )
                        )
                        created_cats += 1
                        existing_cats.add(cat_name)

                    # 3. Generate stable slugs and insert articles
                    existing_arts = set(
                        (await session.execute(select(Article.slug))).scalars().all()
                    )
                    for a in all_articles:
                        base_slug = to_slug(a["title"])
                        if base_slug in existing_arts:
                            skipped += 1
                            continue
                        slug = base_slug
                        suffix = 1
                        while slug in existing_arts:
                            suffix += 1
                            slug = f"{base_slug}-{suffix}"[:80].rstrip("-")

                        if slug in existing_arts:
                            skipped += 1
                            continue

                        session.add(
                            Article(
                                slug=slug,
                                title=a["title"],
                                summary=a.get("summary", ""),
                                body_markdown=a["body_markdown"],
                                audience=a.get("audience", "all"),
                                language=a.get("language", "ru"),
                                category=a.get("category", "Общее"),
                                tags=a.get("tags", []),
                                access_level=a.get("access_level", "PUBLIC"),
                                status=a.get("status", "PUBLISHED"),
                                published_at=now,
                            )
                        )
                        created_arts += 1
                        existing_arts.add(slug)

                    await session.commit()
                    print(
                        f"OK: categories_created={created_cats}, articles_created={created_arts}, "
                        f"articles_skipped={skipped}"
                    )
                except Exception as exc:
                    if not is_seed_source_unavailable(exc):
                        print(f"FAILED to seed actual articles: {exc}")
                        raise

                    print(
                        "WARN: pinned KB seed source is unavailable "
                        f"(bucket={seed_bucket_name()}, prefix={SEED_PREFIX}): {exc}"
                    )
                    published_count = await count_published_articles(session)
                    if published_count >= len(FALLBACK_ARTICLES):
                        print(
                            "Existing published articles found "
                            f"(count={published_count}); keeping current KB content."
                        )
                        return 0

                    print(
                        "Published KB content is empty or partial "
                        f"(count={published_count}); ensuring emergency public FAQ fallback."
                    )
                    fallback_result = await seed_fallback_public_articles(session, now)
                    fallback_cats, fallback_arts, fallback_skipped = fallback_result
                    print(
                        "OK: fallback_categories_created="
                        f"{fallback_cats}, fallback_articles_created={fallback_arts}, "
                        f"fallback_articles_skipped={fallback_skipped}"
                    )
            else:
                print(
                    f"Skipping actual KB seed for local environment: {env} "
                    "(database is cleaned of mock data)."
                )
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
