/**
 * /admin/analytics — in-app KB analytics dashboard (C, 2026-05-28).
 *
 * Three sections:
 * 1. Top search queries (window selectable) с content-gap breakdown.
 *    Visualises «что ищут пользователи» + «какие из этих query'ев
 *    не находят результат» (FTS no-result rate per query).
 * 2. Per-article Q&A counts — moderation backlog signal per статья.
 * 3. Top unanswered chat queries (trend buckets) — что чаще всего
 *    спрашивают в чате без RAG-grounded ответа; quick-link на
 *    moderation queue из #350.
 *
 * Server Component с initial fetch (graceful degradation на ApiError).
 * Window selector — query param `?window_hours=N` (общий для всех
 * window-bound секций).
 */

import Link from "next/link";

import Nav from "@/app/_components/nav";
import {
  getArticleQuestionsCounts,
  getTopQueries,
  getTopUnansweredQueries,
} from "@/lib/api/admin-analytics";
import { ApiError } from "@/lib/api/client";

import UnansweredTrendSection from "./_components/unanswered-trend-section";

interface PageProps {
  searchParams: Promise<{ window_hours?: string }>;
}

const WINDOW_PRESETS: { value: number; label: string }[] = [
  { value: 24, label: "24 ч" },
  { value: 168, label: "7 дн" },
  { value: 720, label: "30 дн" },
];

function parseWindow(raw: string | undefined): number {
  if (!raw) return 168;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 1 || n > 720) return 168;
  return Math.floor(n);
}

export default async function AnalyticsPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const windowHours = parseWindow(params.window_hours);

  let queries;
  let questions;
  let unanswered;
  let error: string | null = null;
  try {
    [queries, questions, unanswered] = await Promise.all([
      getTopQueries({ windowHours, limit: 50 }),
      getArticleQuestionsCounts({ limit: 50 }),
      getTopUnansweredQueries({ windowHours, limit: 50, status: "NEW" }),
    ]);
  } catch (err) {
    if (err instanceof ApiError) {
      error =
        err.status === 401
          ? "Требуется авторизация."
          : err.status === 403
            ? "Требуется staff_admin scope."
            : `Ошибка ${err.status}`;
      queries = { window_hours: windowHours, data: [] };
      questions = { data: [] };
      unanswered = { window_hours: windowHours, status: "NEW" as const, data: [] };
    } else {
      throw err;
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">
            Аналитика KB
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Реальное использование базы знаний: запросы пользователей,
            content gaps, очередь модерации Q&A.
          </p>
        </header>

        {error ? (
          <p
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </p>
        ) : null}

        {/* Top queries section */}
        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Топ поисковых запросов</h2>
            <nav className="flex gap-2">
              {WINDOW_PRESETS.map((p) => {
                const active = p.value === windowHours;
                return (
                  <Link
                    key={p.value}
                    href={`/admin/analytics?window_hours=${p.value}`}
                    className={`rounded-md px-2 py-1 text-xs ${
                      active
                        ? "bg-brand text-ink"
                        : "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
                    }`}
                  >
                    {p.label}
                  </Link>
                );
              })}
            </nav>
          </div>
          {queries.data.length === 0 ? (
            <p className="rounded-md border border-gray-200 bg-white p-4 text-sm text-gray-600">
              Нет запросов за выбранный период (window={windowHours} ч).
            </p>
          ) : (
            <table className="w-full overflow-hidden rounded-md border border-gray-200 bg-white text-sm">
              <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wider text-gray-600">
                <tr>
                  <th className="px-3 py-2">Запрос</th>
                  <th className="px-3 py-2 text-right">Всего</th>
                  <th className="px-3 py-2 text-right">С результатами</th>
                  <th className="px-3 py-2 text-right">Без результатов</th>
                  <th className="px-3 py-2 text-right">Gap rate</th>
                </tr>
              </thead>
              <tbody>
                {queries.data.map((q) => {
                  const gapRate = q.total > 0 ? q.without_results / q.total : 0;
                  const isContentGap = gapRate >= 0.5;
                  return (
                    <tr
                      key={q.query}
                      className="border-t border-gray-100 even:bg-gray-50/30"
                    >
                      <td className="px-3 py-2 font-mono text-xs text-gray-800">
                        {q.query}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-700">
                        {q.total}
                      </td>
                      <td className="px-3 py-2 text-right text-green-700">
                        {q.with_results}
                      </td>
                      <td className="px-3 py-2 text-right text-orange-700">
                        {q.without_results}
                      </td>
                      <td
                        className={`px-3 py-2 text-right ${isContentGap ? "font-medium text-red-700" : "text-gray-500"}`}
                      >
                        {(gapRate * 100).toFixed(0)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          <p className="text-xs text-gray-500">
            «Gap rate» {">"} 50% = content gap candidate; рассмотрите
            создание/доработку статьи под эти запросы.
          </p>
        </section>

        {/* Q&A per-article section */}
        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Q&A: модерация по статьям</h2>
            <Link
              href="/admin/article-questions?status=PENDING"
              className="text-sm text-brand-strong hover:underline"
            >
              Очередь модерации →
            </Link>
          </div>
          {questions.data.length === 0 ? (
            <p className="rounded-md border border-gray-200 bg-white p-4 text-sm text-gray-600">
              Пока нет вопросов от пользователей.
            </p>
          ) : (
            <table className="w-full overflow-hidden rounded-md border border-gray-200 bg-white text-sm">
              <thead className="bg-gray-50 text-left text-xs font-medium uppercase tracking-wider text-gray-600">
                <tr>
                  <th className="px-3 py-2">Статья</th>
                  <th className="px-3 py-2 text-right">Новые</th>
                  <th className="px-3 py-2 text-right">Отвеченные</th>
                  <th className="px-3 py-2 text-right">Отклонённые</th>
                  <th className="px-3 py-2 text-right">Всего</th>
                </tr>
              </thead>
              <tbody>
                {questions.data.map((a) => (
                  <tr
                    key={a.article_id}
                    className="border-t border-gray-100 even:bg-gray-50/30"
                  >
                    <td className="px-3 py-2">
                      <Link
                        href={`/articles/${encodeURIComponent(a.slug)}`}
                        className="text-brand-strong hover:underline"
                      >
                        {a.title}
                      </Link>
                    </td>
                    <td
                      className={`px-3 py-2 text-right ${a.pending > 0 ? "font-medium text-yellow-700" : "text-gray-500"}`}
                    >
                      {a.pending}
                    </td>
                    <td className="px-3 py-2 text-right text-green-700">
                      {a.answered}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-500">
                      {a.dismissed}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-700">
                      {a.total}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="text-xs text-gray-500">
            Статьи отсортированы по количеству PENDING вопросов — содержательный
            backlog модерации сверху.
          </p>
        </section>

        <UnansweredTrendSection
          data={unanswered.data}
          windowHours={windowHours}
        />
      </main>
    </>
  );
}
