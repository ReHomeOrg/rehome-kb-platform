/**
 * Security incidents table (#249).
 */

import type { IncidentSeverity, SecurityIncident } from "@/lib/api/types";

interface Props {
  incidents: SecurityIncident[];
  error?: string | undefined;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { hour12: false });
}

function severityBadge(s: IncidentSeverity): JSX.Element {
  const colors: Record<IncidentSeverity, string> = {
    critical: "bg-red-100 text-red-900",
    high: "bg-orange-100 text-orange-900",
    medium: "bg-yellow-100 text-yellow-900",
    low: "bg-gray-100 text-gray-800",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[s]}`}>
      {s}
    </span>
  );
}

function statusBadge(status: SecurityIncident["status"]): JSX.Element {
  const colors: Record<SecurityIncident["status"], string> = {
    OPEN: "bg-blue-100 text-blue-800",
    INVESTIGATING: "bg-indigo-100 text-indigo-800",
    RESOLVED: "bg-green-100 text-green-800",
    FALSE_POSITIVE: "bg-gray-100 text-gray-700",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[status]}`}>
      {status}
    </span>
  );
}

function rknCell(incident: SecurityIncident): JSX.Element {
  if (!incident.rkn_notification_required) {
    return <span className="text-gray-400">—</span>;
  }
  if (incident.rkn_notified_at === null) {
    return (
      <span className="font-medium text-red-700" aria-label="РКН не уведомлён">
        требуется
      </span>
    );
  }
  return (
    <span className="text-green-700" aria-label="РКН уведомлён">
      {formatDateTime(incident.rkn_notified_at)}
    </span>
  );
}

export default function SecurityIncidentsTable({
  incidents,
  error,
}: Props): JSX.Element {
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
  if (incidents.length === 0) {
    return (
      <div className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Инцидентов нет.
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
            <th className="px-3 py-2">Severity</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Обнаружен</th>
            <th className="px-3 py-2">Источник</th>
            <th className="px-3 py-2">РКН уведомление</th>
            <th className="px-3 py-2">Резолюция</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((i) => (
            <tr key={i.id} className="border-t border-gray-100">
              <td className="px-3 py-2 font-mono">
                <a
                  href={`/admin/security-incidents/${i.id}`}
                  className="text-blue-700 hover:underline"
                >
                  {i.id.slice(0, 8)}
                </a>
              </td>
              <td className="px-3 py-2">{i.incident_type}</td>
              <td className="px-3 py-2">{severityBadge(i.severity)}</td>
              <td className="px-3 py-2">{statusBadge(i.status)}</td>
              <td className="px-3 py-2 text-gray-700">
                {formatDateTime(i.detected_at)}
              </td>
              <td className="px-3 py-2 text-gray-700">{i.detected_by}</td>
              <td className="px-3 py-2">{rknCell(i)}</td>
              <td className="px-3 py-2 text-gray-700">
                {i.resolved_at ? formatDateTime(i.resolved_at) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
