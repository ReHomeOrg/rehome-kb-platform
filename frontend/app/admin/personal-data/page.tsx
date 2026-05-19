/**
 * /admin/personal-data — ФЗ-152 §15 SAR admin UI (#250, backend #232).
 *
 * staff_admin scope (STAFF + LEGAL). Non-admin → 403 → graceful message.
 *
 * ФЗ-152 invariant: оператор обязан ответить в 30 дней с момента
 * получения запроса. UI выделяет OVERDUE rows и считает count'ы
 * по статусам.
 *
 * PATCH (обработка заявки) — backlog: CSRF + confirmation flow для
 * resolved_at + assignee selector.
 */

import Nav from "@/app/_components/nav";
import { listPdRequests } from "@/lib/api/admin-pd-requests";
import { ApiError } from "@/lib/api/client";
import type {
  PdRequestStatus,
  PdRequestType,
  PersonalDataRequest,
} from "@/lib/api/types";

import PdRequestsTable from "./_components/pd-requests-table";

interface PageProps {
  searchParams: Promise<{
    status?: string;
    type?: string;
  }>;
}

const VALID_STATUSES: PdRequestStatus[] = [
  "NEW",
  "IN_PROGRESS",
  "COMPLETED",
  "REJECTED",
  "OVERDUE",
];
const VALID_TYPES: PdRequestType[] = ["provide", "correct", "delete", "transfer"];

function parseStatus(s: string | undefined): PdRequestStatus | undefined {
  if (s && (VALID_STATUSES as readonly string[]).includes(s)) {
    return s as PdRequestStatus;
  }
  return undefined;
}

function parseType(s: string | undefined): PdRequestType | undefined {
  if (s && (VALID_TYPES as readonly string[]).includes(s)) {
    return s as PdRequestType;
  }
  return undefined;
}

export default async function PdRequestsPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const status = parseStatus(params.status);
  const type = parseType(params.type);

  let requests: PersonalDataRequest[] = [];
  let error: string | undefined;
  try {
    const body = await listPdRequests({ status, type });
    requests = body.data;
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401 || e.status === 403) {
        error = "Доступ только для staff_admin.";
      } else {
        error = `Ошибка ${e.status}: ${e.message}`;
      }
    } else {
      error = "Не удалось загрузить заявки.";
    }
  }

  const overdueCount = requests.filter((r) => r.status === "OVERDUE").length;
  const activeCount = requests.filter(
    (r) => r.status === "NEW" || r.status === "IN_PROGRESS",
  ).length;

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <h1 className="mb-2 text-2xl font-semibold">
          Заявки субъектов ПДн (ФЗ-152 §15)
        </h1>
        <p className="mb-4 text-sm text-gray-600">
          SLA: 30 дней с момента получения. OVERDUE — автоматический
          статус, выставляется worker&apos;ом (backlog) или ручным review.
        </p>
        <div className="mb-4 flex flex-wrap gap-3 text-xs">
          <span className="rounded-md bg-blue-50 px-3 py-1.5 text-blue-900">
            Активных: {activeCount}
          </span>
          {overdueCount > 0 ? (
            <span
              role="alert"
              className="rounded-md bg-red-50 px-3 py-1.5 font-medium text-red-900"
            >
              OVERDUE: {overdueCount}
            </span>
          ) : null}
        </div>
        <form
          method="get"
          action="/admin/personal-data"
          role="search"
          aria-label="Request filters"
          className="mb-4 flex flex-wrap items-end gap-3 rounded-md border border-gray-200 bg-gray-50 p-3"
        >
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-600">Status</span>
            <select
              name="status"
              defaultValue={status ?? ""}
              aria-label="Filter by status"
              className="w-36 rounded-md border border-gray-300 px-2 py-1 text-xs"
            >
              <option value="">все</option>
              <option value="NEW">NEW</option>
              <option value="IN_PROGRESS">IN_PROGRESS</option>
              <option value="COMPLETED">COMPLETED</option>
              <option value="REJECTED">REJECTED</option>
              <option value="OVERDUE">OVERDUE</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-600">Тип</span>
            <select
              name="type"
              defaultValue={type ?? ""}
              aria-label="Filter by type"
              className="w-36 rounded-md border border-gray-300 px-2 py-1 text-xs"
            >
              <option value="">все</option>
              <option value="provide">provide</option>
              <option value="correct">correct</option>
              <option value="delete">delete</option>
              <option value="transfer">transfer</option>
            </select>
          </label>
          <button
            type="submit"
            className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
          >
            Применить
          </button>
          {status || type ? (
            <a
              href="/admin/personal-data"
              aria-label="Reset filters"
              className="text-xs text-blue-700 underline hover:text-blue-900"
            >
              Сбросить
            </a>
          ) : null}
        </form>
        <PdRequestsTable requests={requests} error={error} />
      </main>
    </>
  );
}
