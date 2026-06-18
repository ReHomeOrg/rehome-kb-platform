/**
 * /admin/users — read-only KB staff users list (#253, backend #230).
 *
 * staff_admin scope. POST/PATCH/DELETE forms — backlog (CSRF +
 * confirmation flow для deactivation).
 */

import Nav from "@/app/_components/nav";
import { listKbUsers } from "@/lib/api/admin-users";
import { ApiError } from "@/lib/api/client";
import type {
  KbUser,
  KbUserRole,
  KbUserStatus,
} from "@/lib/api/types";

import KbUsersTable from "./_components/kb-users-table";

interface PageProps {
  searchParams: Promise<{
    role?: string;
    status?: string;
  }>;
}

const VALID_ROLES: KbUserRole[] = [
  "staff_support",
  "staff_legal",
  "staff_hr",
  "staff_admin",
];
const VALID_STATUSES: KbUserStatus[] = ["ACTIVE", "SUSPENDED", "ARCHIVED"];

function parseRole(s: string | undefined): KbUserRole | undefined {
  if (s && (VALID_ROLES as readonly string[]).includes(s)) {
    return s as KbUserRole;
  }
  return undefined;
}

function parseStatus(s: string | undefined): KbUserStatus | undefined {
  if (s && (VALID_STATUSES as readonly string[]).includes(s)) {
    return s as KbUserStatus;
  }
  return undefined;
}

export default async function KbUsersPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const role = parseRole(params.role);
  const status = parseStatus(params.status);

  let users: KbUser[] = [];
  let error: string | undefined;
  try {
    const body = await listKbUsers({ role, status });
    users = body.data;
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 401 || e.status === 403) {
        error = "Доступ только для staff_admin.";
      } else {
        error = `Ошибка ${e.status}: ${e.message}`;
      }
    } else {
      error = "Не удалось загрузить пользователей.";
    }
  }

  const activeCount = users.filter((u) => u.status === "ACTIVE").length;
  const mfaNotEnabled = users.filter(
    (u) => u.status === "ACTIVE" && !u.mfa_enabled,
  ).length;

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <div className="mb-2 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">KB users (staff)</h1>
          <a
            href="/admin/users/new"
            className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-ink hover:bg-brand-hover"
          >
            + Новый
          </a>
        </div>
        <p className="mb-4 text-sm text-gray-600">
          Сотрудники с правами в kb-модуле (НЕ конечные пользователи
          rehome.one — те живут в основной системе).
        </p>
        <div className="mb-4 flex flex-wrap gap-3 text-xs">
          <span className="rounded-md bg-gray-50 px-3 py-1.5 text-gray-700">
            Активных: {activeCount}
          </span>
          {mfaNotEnabled > 0 ? (
            <span
              role="alert"
              className="rounded-md bg-amber-50 px-3 py-1.5 font-medium text-amber-900"
            >
              ⚠ Без MFA: {mfaNotEnabled}
            </span>
          ) : null}
        </div>
        <form
          method="get"
          action="/admin/users"
          role="search"
          aria-label="User filters"
          className="mb-4 flex flex-wrap items-end gap-3 rounded-md border border-gray-200 bg-gray-50 p-3"
        >
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-600">Role</span>
            <select
              name="role"
              defaultValue={role ?? ""}
              aria-label="Filter by role"
              className="w-44 rounded-md border border-gray-300 px-2 py-1 text-xs"
            >
              <option value="">все</option>
              <option value="staff_admin">staff_admin</option>
              <option value="staff_legal">staff_legal</option>
              <option value="staff_hr">staff_hr</option>
              <option value="staff_support">staff_support</option>
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
              <option value="ACTIVE">ACTIVE</option>
              <option value="SUSPENDED">SUSPENDED</option>
              <option value="ARCHIVED">ARCHIVED</option>
            </select>
          </label>
          <button
            type="submit"
            className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-ink hover:bg-brand-hover"
          >
            Применить
          </button>
          {role || status ? (
            <a
              href="/admin/users"
              aria-label="Reset filters"
              className="text-xs text-brand-strong underline hover:text-ink"
            >
              Сбросить
            </a>
          ) : null}
        </form>
        <KbUsersTable users={users} error={error} />
      </main>
    </>
  );
}
