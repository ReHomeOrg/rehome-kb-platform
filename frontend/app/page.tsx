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
import { listArticles } from "@/lib/api/articles";
import type { ArticleSummary } from "@/lib/api/types";

// 11 категорий из ПЗ «База знаний v1.4» §2. Иконки — emoji для simplicity.
const CATEGORIES: { name: string; emoji: string; description: string }[] = [
  { name: "Начало работы и регистрация", emoji: "👋", description: "Регистрация, верификация, типы аккаунтов" },
  { name: "Поиск и выбор квартиры", emoji: "🔍", description: "Фильтры, объявления, просмотр" },
  { name: "Бронирование и договор", emoji: "📝", description: "Бронь, договор найма, КЭП" },
  { name: "Платежи и финансы", emoji: "💳", description: "Сервисный сбор, оплата, налоги" },
  { name: "Заезд и приёмка квартиры", emoji: "🔑", description: "Передача ключей, акт, ремонт" },
  { name: "Проживание и эксплуатация", emoji: "🏠", description: "Правила, ремонт, аварии" },
  { name: "Коммунальные услуги", emoji: "💡", description: "Счётчики, оплата, провайдеры" },
  { name: "Услуги и коллаборанты", emoji: "🛠️", description: "Уборка, ремонт, доп. сервисы" },
  { name: "Выезд и расторжение", emoji: "🚪", description: "Уведомление, депозит, акт" },
  { name: "Для собственников", emoji: "🏢", description: "Размещение, проверка, выплаты" },
  { name: "Безопасность, данные и поддержка", emoji: "🛡️", description: "ФЗ-152, инциденты, поддержка" },
];

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

export default async function Home(): Promise<JSX.Element> {
  const cookieStore = await cookies();
  const isLoggedIn = cookieStore.has(COOKIE_SESSION);

  const topFaq = await loadTopFaq();

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col px-6 py-12">
      {/* Header */}
      <header className="mb-12 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">help.rehome.one</h1>
          <p className="mt-1 text-sm text-gray-600">
            Справочник, FAQ и помощник по аренде жилья
          </p>
        </div>
        {isLoggedIn ? (
          <form action="/api/auth/logout" method="post">
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
            className="rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800"
          >
            Войти
          </Link>
        )}
      </header>

      {/* Hero + search */}
      <section className="mb-12 rounded-lg border border-gray-200 bg-gradient-to-br from-blue-50 to-gray-50 p-8">
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
            className="flex-1 rounded-md border border-gray-300 px-4 py-2.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
          <button
            type="submit"
            className="rounded-md bg-gray-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-gray-800"
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
              className="text-sm text-blue-600 hover:underline"
            >
              Все FAQ →
            </Link>
          </div>
          <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
            {topFaq.map((a) => (
              <li key={a.slug}>
                <Link
                  href={`/articles/${a.slug}`}
                  className="block rounded-md border border-gray-200 bg-white p-3 hover:border-blue-300 hover:bg-blue-50/30"
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
            className="text-sm text-blue-600 hover:underline"
          >
            Все статьи →
          </Link>
        </div>
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {CATEGORIES.map((c) => (
            <li key={c.name}>
              <Link
                href={`/articles?category=${encodeURIComponent(c.name)}`}
                className="block h-full rounded-md border border-gray-200 bg-white p-4 hover:border-blue-300 hover:bg-blue-50/30"
              >
                <p className="text-2xl">{c.emoji}</p>
                <p className="mt-2 text-sm font-medium text-gray-900">{c.name}</p>
                <p className="mt-1 text-xs text-gray-600">{c.description}</p>
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
          <Link href="/articles?category=Безопасность%2C+данные+и+поддержка" className="underline">
            Политика обработки ПДн (ФЗ-152)
          </Link>
        </p>
      </footer>
    </main>
  );
}
