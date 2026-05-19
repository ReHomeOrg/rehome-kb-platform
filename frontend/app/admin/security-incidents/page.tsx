/**
 * /admin/security-incidents — ФЗ-152 §17.1 incidents UI (#249, backend #231).
 *
 * staff_admin scope (backend gate STAFF + LEGAL). Non-admin → 403 →
 * graceful UX message.
 *
 * РКН notification queue — highlighted (high/critical с
 * rkn_notification_required=true и rkn_notified_at=null).
 *
 * PATCH endpoint (resolve / update status) — backlog: нужен CSRF +
 * confirmation flow для resolved_at + RKN notification timestamp.
 */

import Nav from "@/app/_components/nav";
import { listSecurityIncidents } from "@/lib/api/admin-security-incidents";
import { ApiError } from "@/lib/api/client";
import type {
  IncidentSeverity,
  IncidentStatus,
  SecurityIncident,
} from "@/lib/api/types";

import SecurityIncidentsTable from "./_components/security-incidents-table";

interface PageProps {
  searchParams: Promise<{
    severity?: string;
    status?: string;
  }>;
}

const VALID_SEVERITIES: IncidentSeverity[] = ["low", "medium", "high", "critical"];
const VALID_STATUSES: IncidentStatus[] = [
  "OPEN",
  "INVESTIGATING",
  "RESOLVED",
  "FALSE_POSITIVE",
];

function parseSeverity(s: string | undefined): IncidentSeverity | undefined {
  if (s && (VALID_SEVERITIES as readonly string[]).includes(s)) {
    return s as IncidentSeverity;
  }
  return undefined;
}

function parseStatus(s: string | undefined): IncidentStatus | undefined {
  if (s && (VALID_STATUSES as readonly string[]).includes(s)) {
    return s as IncidentStatus;
  }
  return undefined;
}

export default async function SecurityIncidentsPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const severity = parseSeverity(params.severity);
  const status = parseStatus(params.status);

  let incidents: SecurityIncident[] = [];
  let error: string | undefined;
  try {
    const body = await listSecurityIncidents({ severity, status });
    incidents = body.data;
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401 || e.status === 403) {
        error = "Доступ только для staff_admin.";
      } else {
        error = `Ошибка ${e.status}: ${e.message}`;
      }
    } else {
      error = "Не удалось загрузить инциденты.";
    }
  }

  const rknPending = incidents.filter(
    (i) => i.rkn_notification_required && i.rkn_notified_at === null,
  ).length;

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <h1 className="mb-2 text-2xl font-semibold">Security incidents</h1>
        <p className="mb-4 text-sm text-gray-600">
          ФЗ-152 §17.1 — реестр security событий. РКН notification gate:
          high / critical → notification обязателен в 24h (факт) /
          72h (полный состав).
        </p>
        {rknPending > 0 ? (
          <div
            role="alert"
            className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
          >
            ⚠ {rknPending} инцидент(ов) требуют РКН-уведомления, но
            ещё не отмечены как уведомлённые. Проверьте column
            «РКН уведомление».
          </div>
        ) : null}
        <form
          method="get"
          action="/admin/security-incidents"
          role="search"
          aria-label="Incident filters"
          className="mb-4 flex flex-wrap items-end gap-3 rounded-md border border-gray-200 bg-gray-50 p-3"
        >
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-600">Severity</span>
            <select
              name="severity"
              defaultValue={severity ?? ""}
              aria-label="Filter by severity"
              className="w-36 rounded-md border border-gray-300 px-2 py-1 text-xs"
            >
              <option value="">все</option>
              <option value="critical">critical</option>
              <option value="high">high</option>
              <option value="medium">medium</option>
              <option value="low">low</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-600">Status</span>
            <select
              name="status"
              defaultValue={status ?? ""}
              aria-label="Filter by status"
              className="w-36 rounded-md border border-gray-300 px-2 py-1 text-xs"
            >
              <option value="">все</option>
              <option value="OPEN">OPEN</option>
              <option value="INVESTIGATING">INVESTIGATING</option>
              <option value="RESOLVED">RESOLVED</option>
              <option value="FALSE_POSITIVE">FALSE_POSITIVE</option>
            </select>
          </label>
          <button
            type="submit"
            className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
          >
            Применить
          </button>
          {severity || status ? (
            <a
              href="/admin/security-incidents"
              aria-label="Reset filters"
              className="text-xs text-blue-700 underline hover:text-blue-900"
            >
              Сбросить
            </a>
          ) : null}
        </form>
        <SecurityIncidentsTable incidents={incidents} error={error} />
      </main>
    </>
  );
}
