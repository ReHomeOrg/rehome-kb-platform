/**
 * Personal data requests table (#250).
 */

import type { PdRequestStatus, PersonalDataRequest } from "@/lib/api/types";

interface Props {
  requests: PersonalDataRequest[];
  error?: string | undefined;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { hour12: false });
}

function statusBadge(status: PdRequestStatus): JSX.Element {
  const colors: Record<PdRequestStatus, string> = {
    NEW: "bg-blue-100 text-blue-800",
    IN_PROGRESS: "bg-indigo-100 text-indigo-800",
    COMPLETED: "bg-green-100 text-green-800",
    REJECTED: "bg-gray-100 text-gray-700",
    OVERDUE: "bg-red-100 text-red-800",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[status]}`}>
      {status}
    </span>
  );
}

function dueAtCell(req: PersonalDataRequest): JSX.Element {
  const due = new Date(req.due_at);
  const now = new Date();
  const isOverdue =
    due < now && (req.status === "NEW" || req.status === "IN_PROGRESS");
  return (
    <span className={isOverdue ? "font-medium text-red-700" : "text-gray-700"}>
      {formatDateTime(req.due_at)}
    </span>
  );
}

export default function PdRequestsTable({ requests, error }: Props): JSX.Element {
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
  if (requests.length === 0) {
    return (
      <div className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Заявок нет.
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-md border border-gray-200">
      <table className="w-full text-xs">
        <thead className="bg-gray-50 text-left text-gray-600">
          <tr>
            <th className="px-3 py-2">ID</th>
            <th className="px-3 py-2">Тип</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Subject</th>
            <th className="px-3 py-2">Создана</th>
            <th className="px-3 py-2">Срок (30д)</th>
            <th className="px-3 py-2">Закрыта</th>
            <th className="px-3 py-2">Assignee</th>
          </tr>
        </thead>
        <tbody>
          {requests.map((r) => (
            <tr key={r.id} className="border-t border-gray-100">
              <td className="px-3 py-2 font-mono">{r.id.slice(0, 8)}</td>
              <td className="px-3 py-2">{r.type}</td>
              <td className="px-3 py-2">{statusBadge(r.status)}</td>
              <td className="px-3 py-2 text-gray-700">
                {r.subject_email ?? r.subject_phone ?? r.subject_id.slice(0, 8)}
              </td>
              <td className="px-3 py-2 text-gray-700">{formatDateTime(r.created_at)}</td>
              <td className="px-3 py-2">{dueAtCell(r)}</td>
              <td className="px-3 py-2 text-gray-700">
                {r.completed_at ? formatDateTime(r.completed_at) : "—"}
              </td>
              <td className="px-3 py-2 font-mono text-gray-500">
                {r.assigned_to ? r.assigned_to.slice(0, 8) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
