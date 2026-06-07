"""Seed a small set of PUBLIC reHome FAQ articles + categories (local demo).

For the reHome integration (Slice 1): gives the embedded Help-center + RAG chat
real, anonymous-visible content without needing the MinIO kb-seed bucket
(ADR-0027) or STAFF auth. Writes via ORM directly (bypasses STAFF-only API).

Idempotent: re-running skips slugs that already exist.

Run inside the kb-backend container (scripts/ bind-mounted at /app/scripts):
    docker compose -f docker-compose.kb-local.yml exec kb-backend \
        python -m scripts.seed_rehome_faq
Then index for RAG:
    docker compose -f docker-compose.kb-local.yml exec kb-backend \
        python -m scripts.reindex_articles
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://kb:kb@postgres-kb:5432/rehome_kb")

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.api.articles.models import Article
from src.api.categories.models import Category

CATEGORIES: list[dict[str, str]] = [
    {"slug": "arenda", "title": "Аренда жилья", "description": "Поиск, бронирование и заселение."},
    {"slug": "platezhi", "title": "Оплата и эскроу", "description": "Платежи, гарантии, возврат залога."},
    {"slug": "verifikatsiya", "title": "Верификация и KYC", "description": "Подтверждение личности и собственника."},
    {"slug": "dogovor", "title": "Договор найма", "description": "Условия, подписание и расторжение."},
]

# (slug, title, category_slug, summary, body_markdown, tags)
ARTICLES: list[dict] = [
    {
        "slug": "kak-zabronirovat-kvartiru",
        "title": "Как забронировать квартиру",
        "category": "arenda",
        "summary": "Пошагово: от поиска объекта до подтверждённой брони.",
        "tags": ["бронирование", "аренда", "начало"],
        "body_markdown": (
            "## Как забронировать квартиру в reHome\n\n"
            "1. Найдите подходящий объект в каталоге и откройте его карточку.\n"
            "2. Нажмите **«Забронировать»** и выберите даты заселения.\n"
            "3. Пройдите проверку личности (KYC), если ещё не проходили.\n"
            "4. Дождитесь подтверждения от собственника.\n\n"
            "После подтверждения бронь переходит в статус активной, и вы можете "
            "перейти к подписанию договора найма и оплате."
        ),
    },
    {
        "slug": "kak-vernut-zalog",
        "title": "Как вернуть залог",
        "category": "platezhi",
        "summary": "Когда и как возвращается обеспечительный платёж после выезда.",
        "tags": ["залог", "возврат", "выезд", "оплата"],
        "body_markdown": (
            "## Возврат залога\n\n"
            "Обеспечительный платёж (залог) хранится на эскроу-счёте и "
            "возвращается после выезда при отсутствии претензий.\n\n"
            "**Порядок возврата:**\n\n"
            "1. Подпишите акт приёма-передачи при выезде.\n"
            "2. Собственник проверяет состояние квартиры.\n"
            "3. Если претензий нет — залог возвращается на вашу карту в течение "
            "нескольких рабочих дней.\n\n"
            "Если возник спор по состоянию квартиры, возврат залога "
            "приостанавливается до разбирательства."
        ),
    },
    {
        "slug": "chto-takoe-eskrou",
        "title": "Что такое эскроу и зачем оно нужно",
        "category": "platezhi",
        "summary": "Как reHome защищает деньги нанимателя и собственника.",
        "tags": ["эскроу", "безопасность", "оплата"],
        "body_markdown": (
            "## Эскроу в reHome\n\n"
            "Эскроу — это защищённый счёт, на котором деньги удерживаются до "
            "выполнения условий сделки. Наниматель вносит оплату, но собственник "
            "получает её только после заселения и подтверждения.\n\n"
            "Это защищает обе стороны: наниматель уверен, что деньги не уйдут до "
            "заселения, а собственник — что оплата гарантирована."
        ),
    },
    {
        "slug": "kak-projti-verifikaciyu",
        "title": "Как пройти верификацию личности",
        "category": "verifikatsiya",
        "summary": "Подтверждение личности через банк или оператора связи.",
        "tags": ["kyc", "верификация", "паспорт"],
        "body_markdown": (
            "## Верификация личности (KYC)\n\n"
            "Перед бронированием необходимо подтвердить личность. reHome "
            "поддерживает несколько способов:\n\n"
            "- через мобильного оператора (МТС);\n"
            "- через банк (Сбер, Т-Банк);\n"
            "- вводом паспортных данных вручную (для собственников).\n\n"
            "Проверка занимает от нескольких секунд до пары минут. После успешной "
            "верификации ваш профиль получает статус «подтверждён»."
        ),
    },
    {
        "slug": "kak-podpisat-dogovor",
        "title": "Как подписать договор найма",
        "category": "dogovor",
        "summary": "Электронная подпись договора по SMS-коду.",
        "tags": ["договор", "подпись", "sms"],
        "body_markdown": (
            "## Подписание договора найма\n\n"
            "Договор найма подписывается электронно:\n\n"
            "1. Откройте сформированный договор в разделе сделки.\n"
            "2. Внимательно проверьте условия (сроки, сумма, адрес).\n"
            "3. Нажмите **«Подписать»** — на ваш телефон придёт SMS-код.\n"
            "4. Введите код для подтверждения подписи.\n\n"
            "Обе стороны (наниматель и собственник) подписывают договор своими "
            "кодами. После этого договор считается заключённым."
        ),
    },
    {
        "slug": "kak-rastorgnut-dogovor",
        "title": "Как досрочно расторгнуть договор",
        "category": "dogovor",
        "summary": "Условия и порядок досрочного расторжения найма.",
        "tags": ["договор", "расторжение", "выезд"],
        "body_markdown": (
            "## Досрочное расторжение договора\n\n"
            "Досрочно расторгнуть договор можно по соглашению сторон или в "
            "случаях, предусмотренных договором.\n\n"
            "1. Уведомите вторую сторону через платформу заранее (срок указан "
            "в договоре).\n"
            "2. Согласуйте дату выезда и подпишите акт приёма-передачи.\n"
            "3. После проверки квартиры производится взаиморасчёт и возврат "
            "залога.\n\n"
            "Если согласия достичь не удаётся, обращение передаётся в поддержку "
            "для разбирательства."
        ),
    },
]


async def main() -> int:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    created_cats = created_arts = skipped = 0
    now = datetime.now(timezone.utc)
    
    env = os.environ.get("REHOME_ENV", "dev").lower()
    
    try:
        async with factory() as session:
            if env in ("prod", "staging"):
                print(f"Running ACTUAL KB seed for environment: {env}")
                try:
                    from scripts.import_kb_articles import parse_faq, parse_kb, fetch_source, to_slug
                    
                    # 1. Fetch and parse actual articles from S3/MinIO
                    faq_bytes, _ = fetch_source("seed://reHome_FAQ_топ15.docx")
                    kb_bytes, _ = fetch_source("seed://reHome_База_статей_120.docx")
                    
                    faq_articles = parse_faq(faq_bytes)
                    kb_articles = parse_kb(kb_bytes)
                    all_articles = faq_articles + kb_articles
                    
                    # 2. Extract and insert unique categories
                    existing_cats = set(
                        (await session.execute(select(Category.slug))).scalars().all()
                    )
                    unique_categories = set(a["category"] for a in all_articles if a.get("category"))
                    for cat_name in unique_categories:
                        if cat_name in existing_cats:
                            continue
                        session.add(Category(slug=cat_name, title=cat_name, description=f"Статьи из категории {cat_name}"))
                        created_cats += 1
                        existing_cats.add(cat_name)
                        
                    # 3. Generate stable slugs and insert articles
                    existing_arts = set(
                        (await session.execute(select(Article.slug))).scalars().all()
                    )
                    for a in all_articles:
                        base_slug = to_slug(a["title"])
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
                    print(f"FAILED to seed actual articles: {exc}")
                    # We print the error but do not crash the script to avoid breaking deployments,
                    # similar to the legacy || true safety fallback.
                    return 1
            else:
                # Local dev mock seeding
                print(f"Running MOCK KB seed for environment: {env}")
                existing_cats = set(
                    (await session.execute(select(Category.slug))).scalars().all()
                )
                for c in CATEGORIES:
                    if c["slug"] in existing_cats:
                        continue
                    session.add(Category(slug=c["slug"], title=c["title"], description=c["description"]))
                    created_cats += 1

                existing_arts = set(
                    (await session.execute(select(Article.slug))).scalars().all()
                )
                for a in ARTICLES:
                    if a["slug"] in existing_arts:
                        skipped += 1
                        continue
                    session.add(
                        Article(
                            slug=a["slug"],
                            title=a["title"],
                            summary=a["summary"],
                            body_markdown=a["body_markdown"],
                            audience="all",
                            language="ru",
                            category=a["category"],
                            tags=a["tags"],
                            access_level="PUBLIC",
                            status="PUBLISHED",
                            published_at=now,
                        )
                    )
                    created_arts += 1

                await session.commit()
                print(
                    f"OK: categories_created={created_cats}, articles_created={created_arts}, "
                    f"articles_skipped={skipped}"
                )
    finally:
        await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
