"""Засидить категории базы знаний из секционных заголовков мастер-документа.

Мастер-документ v6.5 размечает категории заголовками вида
"## <Название>  (`slug`)" (например "## Агенты reHome  (`12_agents`)").
`import_kb_markdown` этот формат не распознаёт (ждёт `### Категория ...`),
поэтому категории нужно засидить отдельно — иначе новые разделы
(12_agents, 13_claims, 14_glossary, 15_support) не получают строку в
`categories`, и их страницы-категории пусты.

Сидинг **create-missing**: существующие slug'и не трогаются (идемпотентно),
создаются только отсутствующие. На БД с уже заведёнными 1–11 это добавит
ровно 12–15.

Запуск:

    python -m scripts.seed_kb_categories scripts/seed/reHome_KB_master_v6.5.md [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from typing import Any

# `## <Название>  (`slug`)`. Заголовки без backtick-слага (`## Часть II...`,
# `## Оглавление`) намеренно не матчатся.
SECTION_CATEGORY_RE = re.compile(
    r"^##\s+(?P<title>.+?)\s+\(`(?P<slug>[^`]+)`\)\s*$",
    flags=re.MULTILINE,
)


def parse_section_categories(path: Path) -> list[dict[str, str]]:
    """Распарсить секционные заголовки категорий из мастер-документа."""
    text = path.read_text(encoding="utf-8")
    categories: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in SECTION_CATEGORY_RE.finditer(text):
        slug = match.group("slug").strip()[:100]
        title = match.group("title").strip()[:200]
        if not slug or slug in seen:
            continue
        seen.add(slug)
        categories.append(
            {
                "slug": slug,
                "title": title,
                "description": f"Статьи из категории «{title}»",
            }
        )
    return categories


async def seed_categories(path: Path) -> int:
    """Создать отсутствующие категории (существующие не трогаются)."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.api.categories.models import Category
    from src.api.config import get_settings

    categories = parse_section_categories(path)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    created = skipped = 0

    async with factory() as session:
        result = await session.execute(
            select(Category.slug).where(Category.slug.in_([c["slug"] for c in categories]))
        )
        existing_slugs = {row[0] for row in result}

        for category in categories:
            if category["slug"] in existing_slugs:
                skipped += 1
                continue
            session.add(Category(**category))
            created += 1

        await session.commit()

    await engine.dispose()
    print(f"OK: categories_created={created}, skipped={skipped}, total={len(categories)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("path", type=Path, help="Путь к мастер-markdown (v6.5)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    categories = parse_section_categories(args.path)
    print(f"Распознано категорий: {len(categories)}")
    for category in categories:
        print(f"  {category['slug']:<13} {category['title']}")
    if args.dry_run:
        return 0
    if not categories:
        return 1
    return asyncio.run(seed_categories(args.path))


if __name__ == "__main__":
    sys.exit(main())
