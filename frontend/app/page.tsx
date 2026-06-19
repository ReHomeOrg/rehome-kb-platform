/**
 * Landing page для help.rehome.one (ПЗ §2).
 *
 * Server Component — рендерит при build/request:
 * - Поисковая строка (Form action → /articles?q=)
 * - 11 категорий из ПЗ (tile grid с counts)
 * - Top FAQ (15 импортированных из reHome_FAQ_топ15) — статьи c
 *   category в FAQ-list
 * - CTA блок «Не нашли ответ? → /chat»
 *
 * Login-state: header показывает «Войти» или «Выйти» (cookie session).
 */

import { cookies } from "next/headers";
import Link from "next/link";

import { COOKIE_SESSION } from "@/lib/auth/cookies";
import { BASE_PATH } from "@/lib/base-path";
import { listCategories } from "@/lib/api/categories";
import { listArticles } from "@/lib/api/articles";
import type { ArticleSummary, Category } from "@/lib/api/types";

type CategoryCard = {
  slug: string;
  title: string;
  emoji: string;
  description: string;
};

const CATEGORY_VISUALS: Record<string, Omit<CategoryCard, "slug" | "title">> = {
  "1_start": { emoji: "👋", description: "Регистрация, верификация, типы аккаунтов" },
  "2_search": { emoji: "🔍", description: "Фильтры, объявления, просмотр" },
  "3_booking": { emoji: "📝", description: "Бронь, договор найма, КЭП" },
  "4_payments": { emoji: "💳", description: "Сервисный сбор, оплата, налоги" },
  "5_movein": { emoji: "🔑", description: "Передача ключей, акт, ремонт" },
  "6_living": { emoji: "🏠", description: "Правила, ремонт, аварии" },
  "7_utilities": { emoji: "💡", description: "Счётчики, оплата, провайдеры" },
  "8_services": { emoji: "🛠️", description: "Уборка, ремонт, доп. сервисы" },
  "9_moveout": { emoji: "🚪", description: "Уведомление, депозит, акт" },
  "10_owners": { emoji: "🏢", description: "Размещение, проверка, выплаты" },
  "11_security": { emoji: "🛡️", description: "ФЗ-152, инциденты, поддержка" },
  "12_agents": { emoji: "🤝", description: "Агенты reHome, агентский договор, отчёты" },
  "13_claims": { emoji: "⚖️", description: "Споры, претензии, гарантийная и компенсационная выплаты" },
  "14_glossary": { emoji: "📖", description: "Термины и определения платформы" },
  "15_support": { emoji: "🛟", description: "Технические вопросы, ошибки, поддержка" },
};

const CATEGORY_ORDER = [
  "1_start",
  "2_search",
  "3_booking",
  "4_payments",
  "5_movein",
  "6_living",
  "7_utilities",
  "8_services",
  "9_moveout",
  "10_owners",
  "11_security",
  "12_agents",
  "13_claims",
  "14_glossary",
  "15_support",
] as const;

// FAQ — пять самых востребованных (по импортированному order'у).
const TOP_FAQ_LIMIT = 6;

async function loadTopFaq(): Promise<ArticleSummary[]> {
  try {
    // FAQ статьи импортируются с тегом `topfaq` (см. tools/import.py).
    // Это позволяет курировать «горячие» FAQ независимо от category mapping'а.
    const resp = await listArticles({
      tags: "topfaq",
      limit: TOP_FAQ_LIMIT,
    });
    return resp.data;
  } catch {
    // Тихо degrade — landing должен рендериться даже если backend down.
    return [];
  }
}

async function loadCategories(): Promise<Category[]> {
  try {
    const resp = await listCategories();
    return resp.data;
  } catch {
    return [];
  }
}

function toCategoryCards(categories: Category[]): CategoryCard[] {
  const bySlug = new Map(categories.map((category) => [category.slug, category] as const));
  const orderedSlugSet = new Set<string>(CATEGORY_ORDER);
  const cards = CATEGORY_ORDER.flatMap((slug) => {
    const category = bySlug.get(slug);
    if (!category) return [];
    const visuals = CATEGORY_VISUALS[slug];
    return [{
      slug,
      title: category.title,
      emoji: visuals.emoji,
      description: visuals.description,
    }];
  });

  const remaining = categories
    .filter((category) => !orderedSlugSet.has(category.slug))
    .map((category) => ({
      slug: category.slug,
      title: category.title,
      emoji: "📚",
      description: category.description ?? "Статьи по этой теме",
    }));

  return [...cards, ...remaining];
}

export default async function Home(): Promise<JSX.Element> {
  const cookieStore = await cookies();
  const isLoggedIn = cookieStore.has(COOKIE_SESSION);

  const [topFaq, categories] = await Promise.all([loadTopFaq(), loadCategories()]);
  const categoryCards = toCategoryCards(categories);

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col px-6 py-12">
      {/* Header */}
      <header className="mb-12 flex items-center justify-between">
        <div>
          {BASE_PATH === "/help" ? (
            // Встроено в платформу (rehome.one/help): значок+надпись reHome
            // как на главной, клик → редирект на главную rehome.one.
            <a
              href="https://rehome.one"
              aria-label="reHome — на главную"
              className="mb-3 inline-flex items-center gap-2 text-lg font-semibold tracking-tight"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src="https://rehome.one/assets/locker-logo-mark.jpg"
                alt=""
                width={28}
                height={28}
                className="h-7 w-7 rounded"
              />
              reHome
            </a>
          ) : null}
          <h1 className="text-3xl font-semibold tracking-tight">help.rehome.one</h1>
          <p className="mt-1 text-sm text-gray-600">
            Справочник, FAQ и помощник по аренде жилья
          </p>
        </div>
        {isLoggedIn ? (
          <form action={`${BASE_PATH}/api/auth/logout`} method="post">
            <button
              type="submit"
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
            >
              Выйти
            </button>
          </form>
        ) : (
          <Link
            href="/login"
            className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-ink hover:bg-brand-hover"
          >
            Войти
          </Link>
        )}
      </header>

      {/* Hero + search */}
      <section className="mb-12 rounded-lg border border-gray-200 bg-gradient-to-br from-brand-soft to-sand p-8">
        <h2 className="text-2xl font-semibold">Как мы можем помочь?</h2>
        <p className="mt-2 text-sm text-gray-700">
          Найдите ответ среди {topFaq.length > 0 ? "сотен" : "наших"} статей или задайте
          вопрос AI-ассистенту.
        </p>
        <form action="/articles" method="get" className="mt-6 flex gap-2">
          <input
            type="search"
            name="q"
            placeholder="Например: сервисный сбор, договор, заезд…"
            className="flex-1 rounded-md border border-gray-300 px-4 py-2.5 text-sm shadow-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/30"
          />
          <button
            type="submit"
            className="rounded-md bg-brand px-5 py-2.5 text-sm font-medium text-ink hover:bg-brand-hover"
          >
            Найти
          </button>
        </form>
      </section>

      {/* Top FAQ */}
      {topFaq.length > 0 ? (
        <section className="mb-12">
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="text-xl font-semibold">Популярные вопросы</h2>
            <Link
              href="/articles?tags=topfaq"
              className="text-sm text-brand-strong hover:underline"
            >
              Все FAQ →
            </Link>
          </div>
          <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {topFaq.map((a) => (
              <li key={a.slug}>
                <Link
                  href={`/articles/${a.slug}`}
                  className="block rounded-md border border-gray-200 bg-white p-3 hover:border-brand hover:bg-brand-soft"
                >
                  <p className="text-sm font-medium text-gray-900">{a.title}</p>
                  {a.tags.length > 0 ? (
                    <p className="mt-1 text-xs text-gray-500">
                      {a.tags.slice(0, 3).join(" · ")}
                    </p>
                  ) : null}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* Categories grid */}
      <section className="mb-12">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-xl font-semibold">Категории</h2>
          <Link
            href="/articles"
            className="text-sm text-brand-strong hover:underline"
          >
            Все статьи →
          </Link>
        </div>
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {categoryCards.map((c) => (
            <li key={c.slug}>
              <Link
                href={`/articles?category=${encodeURIComponent(c.slug)}`}
                aria-label={`Открыть категорию ${c.title}`}
                className="group block h-full rounded-md border border-gray-200 bg-white p-4 transition hover:border-brand hover:bg-brand-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
              >
                <p className="text-2xl">{c.emoji}</p>
                <p className="mt-2 text-sm font-medium text-gray-900">{c.title}</p>
                <p className="mt-1 text-xs text-gray-600">{c.description}</p>
                <div className="mt-4 flex items-center justify-between border-t border-gray-100 pt-3 text-xs font-medium text-brand-strong">
                  <span>Открыть статьи</span>
                  <span className="transition group-hover:translate-x-0.5">→</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {/* AI chat CTA */}
      <section className="mb-12 rounded-lg border border-indigo-200 bg-indigo-50/50 p-6 text-center">
        <p className="text-lg font-medium">Не нашли ответ?</p>
        <p className="mt-1 text-sm text-gray-700">
          Задайте вопрос AI-ассистенту — он ответит цитатами из базы знаний.
        </p>
        <Link
          href="/chat"
          className="mt-4 inline-flex items-center rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          Открыть чат →
        </Link>
      </section>

      <footer className="mt-auto border-t border-gray-200 pt-6 text-xs text-gray-500">
        <p>
          reHome — платформа долгосрочной аренды жилья в РФ.{" "}
          <Link href="/articles?category=11_security" className="underline">
            Политика обработки ПДн (ФЗ-152)
          </Link>
        </p>
      </footer>
    </main>
  );
}
