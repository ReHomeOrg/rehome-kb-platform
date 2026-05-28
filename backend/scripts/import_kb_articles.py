"""Импортер статей из .docx → POST /api/v1/articles.

Парсит два .docx:
1. reHome_FAQ_топ15.docx — 15 FAQ (audience/access_level/tags явно
   указаны).
2. reHome_База_статей_120.docx — 120 KB-статей, organised в 11 категорий.
   Поля q/tags/audience указаны в paragraphs; access_level default PUBLIC.

Slug — transliterate(title) + kebab-case, suffix N если коллизия.
Все статусы → PUBLISHED.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from docx import Document
from transliterate import translit  # type: ignore[import-untyped]

API = "http://localhost:8000/api/v1"
TOKEN = Path("/tmp/.kb-token").read_text().strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

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
    # Drop prefix
    line = re.sub(r"^[^:]+:\s*", "", line)
    line = line.strip("[]").strip()
    tags = []
    for chunk in re.split(r"[«»\"',]", line):
        chunk = chunk.strip()
        if chunk and len(chunk) <= 64:
            tags.append(chunk)
    return tags[:10]  # Cap для sanity


def field_value(line: str, key: str) -> str:
    """Вытаскивает `key: value` из `Compact` paragraph."""
    pattern = rf"^{key}\s*:\s*(.*)$"
    m = re.match(pattern, line.strip(), flags=re.IGNORECASE)
    return m.group(1).strip() if m else ""


def parse_faq(path: str) -> list[dict[str, Any]]:
    """FAQ doc — каждая статья начинается с Heading 2 'FAQ-NNN'.

    Fields в Compact paragraphs (question, category, audience, access_level,
    tags). Тело — short_answer + full_answer + последующие paragraphs.
    """
    doc = Document(path)
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
        if p.style.name == "Heading 2" and text.startswith("FAQ-"):
            flush()
            # `topfaq` tag — landing page «Популярные вопросы» query'ит по нему.
            # Category переопределяется ниже из `category:` line.
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
        # Field lines
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
            # Preserve seed tags ('topfaq') если есть.
            seed = [t for t in cur.get("tags", []) if t not in parsed]
            cur["tags"] = (seed + parsed)[:10]
            continue
        # short_answer / full_answer + body
        if v := field_value(text, "short_answer"):
            body_lines.append(f"**Кратко:** {v}")
            continue
        if v := field_value(text, "full_answer"):
            body_lines.append(v)
            continue
        # Plain body paragraph
        body_lines.append(text)
    flush()
    return articles


def parse_kb(path: str) -> list[dict[str, Any]]:
    """KB doc — категории как Heading 1, статьи как Heading 2 'Статья N'.

    Поля внутри: question, tags, audience. access_level не указан — default
    PUBLIC. Тело — все paragraphs после field-блока.
    """
    doc = Document(path)
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

        # Skip the document's TOC / preface paragraphs by waiting for first
        # «Категория» heading.
        if p.style.name == "Heading 1" and text.startswith("Категория"):
            # Format: "Категория 1. Начало работы и регистрация"
            cat = re.sub(r"^Категория\s*\d+\.\s*", "", text).strip()
            current_category = cat[:100] or current_category
            flush()
            cur = None
            body_lines = []
            continue

        if p.style.name == "Heading 2" and text.startswith("Статья"):
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


def post_article(client: httpx.Client, art: dict[str, Any], used_slugs: set[str]) -> str:
    """POST /api/v1/articles + idempotency on slug collision."""
    base_slug = to_slug(art["title"])
    slug = base_slug
    suffix = 1
    while slug in used_slugs:
        suffix += 1
        slug = f"{base_slug}-{suffix}"[:80].rstrip("-")
    used_slugs.add(slug)

    payload = {**art, "slug": slug}
    resp = client.post(f"{API}/articles", json=payload, headers=HEADERS)
    if resp.status_code == 409:
        # Server already has this slug from previous run
        used_slugs.add(slug)
        return f"DUP {slug}"
    if resp.status_code != 201:
        return f"ERR {resp.status_code} {slug}: {resp.text[:200]}"
    return f"OK  {slug}"


def main() -> int:
    print("Parsing FAQ...")
    faq = parse_faq("/home/evgeniy/Downloads/reHome_FAQ_топ15.docx")
    print(f"  FAQ articles: {len(faq)}")

    print("Parsing KB...")
    kb = parse_kb("/home/evgeniy/Downloads/reHome_База_статей_120.docx")
    print(f"  KB articles: {len(kb)}")

    all_articles = faq + kb
    print(f"\nTotal to import: {len(all_articles)}")
    print(f"Sample article 0: title={all_articles[0]['title'][:60]!r}")
    print(f"                  category={all_articles[0]['category']!r}")
    print(f"                  audience={all_articles[0]['audience']!r}")
    print(f"                  access_level={all_articles[0]['access_level']!r}")
    print(f"                  tags={all_articles[0]['tags']}")
    print(f"                  body chars={len(all_articles[0]['body_markdown'])}")
    print()

    if "--dry-run" in sys.argv:
        return 0

    used_slugs: set[str] = set()
    ok = 0
    fail = 0
    dup = 0
    with httpx.Client(timeout=30.0) as client:
        for i, art in enumerate(all_articles, 1):
            try:
                result = post_article(client, art, used_slugs)
            except Exception as exc:
                result = f"EXC {type(exc).__name__}: {exc}"
            if result.startswith("OK"):
                ok += 1
            elif result.startswith("DUP"):
                dup += 1
            else:
                fail += 1
            if i % 10 == 0 or not result.startswith("OK"):
                print(f"  [{i:3d}/{len(all_articles)}] {result}")
            time.sleep(0.02)

    print(f"\n=== Summary: OK={ok}, DUP={dup}, FAIL={fail} ===")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
