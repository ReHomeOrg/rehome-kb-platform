/**
 * /admin/audit — audit log compliance UI (#166).
 *
 * LEGAL access tier (backend #161 enforce'ит). Non-LEGAL → 403 →
 * graceful UX message. SSR fetches с cookie attach.
 */

import Nav from "@/app/_components/nav";
import { listAudit, type AuditFilters } from "@/lib/api/audit";
import { ApiError } from "@/lib/api/client";

import AuditFiltersBar from "./_components/audit-filters";
import AuditTable from "./_components/audit-table";

interface PageProps {
  searchParams: Promise<{
    actor_sub?: string;
    resource_type?: string;
    resource_id?: string;
    action?: string;
    q?: string;
    since?: string;
    until?: string;
    offset?: string;
  }>;
}

const PAGE_SIZE = 50;

function normalizeIsoInput(s: string | undefined): string | undefined {
  // <input type="datetime-local"> возвращает `YYYY-MM-DDTHH:mm` —
  // backend ожидает ISO 8601 с timezone. Defensive append `:00Z`
  // (assume UTC) — для simplicity local-dev UX.
  if (!s) return undefined;
  if (s.includes("Z") || /[+-]\d{2}:\d{2}$/.test(s)) return s;
  return `${s}:00Z`;
}

export default async function AuditPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const offset = params.offset ? Number(params.offset) : 0;

  const filters: AuditFilters = {
    actor_sub: params.actor_sub || undefined,
    resource_type: params.resource_type || undefined,
    resource_id: params.resource_id || undefined,
    action: params.action || undefined,
    q: params.q || undefined,
    since: normalizeIsoInput(params.since),
    until: normalizeIsoInput(params.until),
    limit: PAGE_SIZE,
    offset: Number.isFinite(offset) && offset >= 0 ? offset : 0,
  };

  let body;
  let error: string | null = null;
  try {
    body = await listAudit(filters);
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 403) {
        error = "Доступ только для роли LEGAL / staff_admin / director.";
      } else if (err.status === 401) {
        error = "Требуется авторизация.";
      } else {
        error = `Ошибка ${err.status}`;
      }
      body = { data: [], pagination: { limit: PAGE_SIZE, offset: 0, count: 0 } };
    } else {
      throw err;
    }
  }

  // Pagination next/prev — query string без `offset` сохраняем + меняем.
  const baseParams = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (k !== "offset" && typeof v === "string" && v) {
      baseParams.set(k, v);
    }
  }
  const prevOffset = Math.max(0, (filters.offset ?? 0) - PAGE_SIZE);
  const nextOffset = (filters.offset ?? 0) + PAGE_SIZE;
  const prevParams = new URLSearchParams(baseParams);
  if (prevOffset > 0) prevParams.set("offset", String(prevOffset));
  const nextParams = new URLSearchParams(baseParams);
  nextParams.set("offset", String(nextOffset));

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-8">
        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
            <p className="mt-1 text-sm text-gray-600">
              Compliance trail ФЗ-152. Каждое write-действие в kb-*
              модулях зафиксировано здесь. Read-only.
            </p>
          </div>
          {/* CSV export (#172) — same filters as JSON view; browser
              triggers download через Content-Disposition attachment.
              Anti-DoS hard cap 10000 rows backend-side. */}
          <a
            href={`/help/api/kb/api/v1/audit-log/export.csv?${baseParams.toString()}`}
            className="shrink-0 rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            ↓ Экспорт CSV
          </a>
        </header>
        <AuditFiltersBar
          initial={{
            actor_sub: params.actor_sub ?? "",
            resource_type: params.resource_type ?? "",
            resource_id: params.resource_id ?? "",
            action: params.action ?? "",
            q: params.q ?? "",
            since: params.since ?? "",
            until: params.until ?? "",
          }}
        />
        {error ? (
          <p className="rounded-md border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-800">
            {error}
          </p>
        ) : (
          <>
            <AuditTable data={body.data} />
            <nav className="flex items-center justify-between text-xs text-gray-600">
              <span>
                {body.pagination.count > 0
                  ? `Записей: ${body.pagination.offset + 1}–${
                      body.pagination.offset + body.pagination.count
                    }`
                  : "Записей нет"}
              </span>
              <div className="flex items-center gap-2">
                {(filters.offset ?? 0) > 0 ? (
                  <a
                    href={`/admin/audit?${prevParams.toString()}`}
                    className="rounded-md border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50"
                  >
                    ← Назад
                  </a>
                ) : null}
                {body.pagination.count >= PAGE_SIZE ? (
                  <a
                    href={`/admin/audit?${nextParams.toString()}`}
                    className="rounded-md border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50"
                  >
                    Вперёд →
                  </a>
                ) : null}
              </div>
            </nav>
          </>
        )}
      </main>
    </>
  );
}
