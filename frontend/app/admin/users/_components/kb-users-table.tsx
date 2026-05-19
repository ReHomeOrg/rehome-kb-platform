/**
 * KB users table (#253).
 */

import type { KbUser, KbUserRole, KbUserStatus } from "@/lib/api/types";

interface Props {
  users: KbUser[];
  error?: string | undefined;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { hour12: false });
}

function roleBadge(role: KbUserRole): JSX.Element {
  const colors: Record<KbUserRole, string> = {
    staff_admin: "bg-red-100 text-red-900",
    staff_legal: "bg-purple-100 text-purple-900",
    staff_hr: "bg-pink-100 text-pink-900",
    staff_support: "bg-blue-100 text-blue-900",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[role]}`}>
      {role}
    </span>
  );
}

function statusBadge(status: KbUserStatus): JSX.Element {
  const colors: Record<KbUserStatus, string> = {
    ACTIVE: "bg-green-100 text-green-800",
    SUSPENDED: "bg-amber-100 text-amber-900",
    ARCHIVED: "bg-gray-100 text-gray-700",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[status]}`}>
      {status}
    </span>
  );
}

export default function KbUsersTable({ users, error }: Props): JSX.Element {
  if (error !== undefined) {
    return (
      <div
        role="alert"
        className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900"
      >
        {error}
      </div>
    );
  }
  if (users.length === 0) {
    return (
      <div className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Пользователей нет.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-md border border-gray-200">
      <table className="w-full text-xs">
        <thead className="bg-gray-50 text-left text-gray-600">
          <tr>
            <th className="px-3 py-2">Email</th>
            <th className="px-3 py-2">Имя</th>
            <th className="px-3 py-2">Role</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">MFA</th>
            <th className="px-3 py-2">Создан</th>
            <th className="px-3 py-2">Последний вход</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-t border-gray-100">
              <td className="px-3 py-2 font-mono text-gray-900">
                <a
                  href={`/admin/users/${u.id}`}
                  className="text-blue-700 hover:underline"
                >
                  {u.email}
                </a>
              </td>
              <td className="px-3 py-2 text-gray-700">{u.full_name}</td>
              <td className="px-3 py-2">{roleBadge(u.role)}</td>
              <td className="px-3 py-2">{statusBadge(u.status)}</td>
              <td className="px-3 py-2">
                {u.mfa_enabled ? (
                  <span className="text-green-700" aria-label="MFA enabled">
                    ✓
                  </span>
                ) : (
                  <span className="text-red-700" aria-label="MFA disabled">
                    ✗
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-gray-700">{formatDateTime(u.created_at)}</td>
              <td className="px-3 py-2 text-gray-700">
                {u.last_login_at ? formatDateTime(u.last_login_at) : "никогда"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
