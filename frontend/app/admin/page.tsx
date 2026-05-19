/**
 * /admin — admin dashboard landing page (#251, backend #227).
 *
 * SSR dashboard с 4 stat panels (content / chat / security / period
 * info) + cross-links на sub-pages.
 *
 * staff_admin / staff_legal scope (backend gate). Non-admin → 403 →
 * graceful message.
 */

import Nav from "@/app/_components/nav";
import { getAdminStats } from "@/lib/api/admin-stats";
import { ApiError } from "@/lib/api/client";
import type { AdminStats } from "@/lib/api/types";

interface PageProps {
  searchParams: Promise<{
    from?: string;
    to?: string;
  }>;
}

function formatPercent(v: number, fractionDigits: number = 1): string {
  return `${(v * 100).toFixed(fractionDigits)}%`;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { hour12: false });
}

function StatTile({
  label,
  value,
  href,
  tone,
}: {
  label: string;
  value: string;
  href?: string;
  tone?: "default" | "warning" | "critical";
}): JSX.Element {
  const tones = {
    default: "bg-gray-50 text-gray-900",
    warning: "bg-amber-50 text-amber-900",
    critical: "bg-red-50 text-red-900",
  } as const;
  const cls = `rounded-md border border-gray-200 p-4 ${tones[tone ?? "default"]}`;
  const body = (
    <>
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </>
  );
  if (href) {
    return (
      <a href={href} className={`${cls} block hover:border-gray-400`}>
        {body}
      </a>
    );
  }
  return <div className={cls}>{body}</div>;
}

export default async function AdminDashboardPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const from = params.from?.trim() || undefined;
  const to = params.to?.trim() || undefined;

  let stats: AdminStats | undefined;
  let error: string | undefined;
  try {
    stats = await getAdminStats({ from, to });
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401 || e.status === 403) {
        error = "Доступ только для staff_admin / staff_legal.";
      } else {
        error = `Ошибка ${e.status}: ${e.message}`;
      }
    } else {
      error = "Не удалось загрузить статистику.";
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-5xl px-4 py-6">
        <h1 className="mb-2 text-2xl font-semibold">Admin dashboard</h1>
        {stats ? (
          <p className="mb-6 text-sm text-gray-600">
            Период: {formatDateTime(stats.period.from)} →{" "}
            {formatDateTime(stats.period.to)}
          </p>
        ) : null}

        {error !== undefined ? (
          <div
            role="alert"
            className="mb-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900"
          >
            {error}
          </div>
        ) : null}

        {stats ? (
          <>
            <section aria-label="Контент" className="mb-6">
              <h2 className="mb-3 text-sm font-medium text-gray-700">Контент</h2>
              <div className="grid grid-cols-3 gap-3">
                <StatTile
                  label="Статьи"
                  value={stats.content.total_articles.toString()}
                  href="/articles"
                />
                <StatTile
                  label="Документы"
                  value={stats.content.total_documents.toString()}
                  href="/documents"
                />
                <StatTile
                  label="DRAFT (review queue)"
                  value={stats.content.pending_reviews.toString()}
                />
              </div>
            </section>

            <section aria-label="Чат" className="mb-6">
              <h2 className="mb-3 text-sm font-medium text-gray-700">Чат</h2>
              <div className="grid grid-cols-3 gap-3">
                <StatTile
                  label="Сессии"
                  value={stats.chat.sessions.toString()}
                />
                <StatTile
                  label="Сообщения"
                  value={stats.chat.messages.toString()}
                />
                <StatTile
                  label="Containment rate"
                  value={formatPercent(stats.chat.containment_rate)}
                />
                <StatTile
                  label="Эскалации"
                  value={stats.chat.escalations.toString()}
                  tone={stats.chat.escalations > 0 ? "warning" : "default"}
                />
                <StatTile
                  label="No-answer (webhook only)"
                  value={stats.chat.no_answer_count.toString()}
                />
                <StatTile
                  label="Средний рейтинг"
                  value={
                    stats.chat.avg_rating === null
                      ? "—"
                      : formatPercent(stats.chat.avg_rating)
                  }
                />
              </div>
            </section>

            <section aria-label="Безопасность / ФЗ-152" className="mb-6">
              <h2 className="mb-3 text-sm font-medium text-gray-700">
                Безопасность / ФЗ-152
              </h2>
              <div className="grid grid-cols-3 gap-3">
                <StatTile
                  label="Открытые инциденты"
                  value={stats.security.open_incidents.toString()}
                  href="/admin/security-incidents?status=OPEN"
                  tone={
                    stats.security.open_incidents > 0 ? "warning" : "default"
                  }
                />
                <StatTile
                  label="Critical incidents"
                  value={stats.security.critical_incidents.toString()}
                  href="/admin/security-incidents?severity=critical"
                  tone={
                    stats.security.critical_incidents > 0
                      ? "critical"
                      : "default"
                  }
                />
                <StatTile
                  label="Просроченные SAR (§15)"
                  value={stats.security.overdue_pd_requests.toString()}
                  href="/admin/personal-data?status=OVERDUE"
                  tone={
                    stats.security.overdue_pd_requests > 0
                      ? "critical"
                      : "default"
                  }
                />
              </div>
            </section>

            <section aria-label="Прочее" className="mb-6">
              <h2 className="mb-3 text-sm font-medium text-gray-700">
                Прочие admin-инструменты
              </h2>
              <ul className="grid grid-cols-2 gap-2 text-sm text-blue-700">
                <li>
                  <a href="/admin/audit" className="underline hover:text-blue-900">
                    Аудит-лог →
                  </a>
                </li>
                <li>
                  <a
                    href="/admin/eval-runs"
                    className="underline hover:text-blue-900"
                  >
                    Eval-стенд →
                  </a>
                </li>
              </ul>
            </section>
          </>
        ) : null}
      </main>
    </>
  );
}
