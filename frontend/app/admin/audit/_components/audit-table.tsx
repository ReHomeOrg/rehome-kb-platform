/**
 * Audit log table (#166).
 *
 * Server Component — read-only render. Metadata column показывает
 * JSON pretty-printed для compliance review (никаких action items
 * — это immutable log).
 */

import type { AuditRecord } from "@/lib/api/types";

interface Props {
  data: AuditRecord[];
}

function formatTs(iso: string): string {
  const d = new Date(iso);
  // Локаль ru-RU + DD.MM.YYYY HH:mm:ss — типичный compliance UX.
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}

export default function AuditTable({ data }: Props): JSX.Element {
  if (data.length === 0) {
    return (
      <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Записей не найдено по заданным фильтрам.
      </p>
    );
  }
  return (
    <table className="w-full table-auto border-collapse text-xs">
      <thead>
        <tr className="border-b border-gray-300 text-left uppercase text-gray-500">
          <th className="py-2 pr-3">Время</th>
          <th className="py-2 pr-3">Actor</th>
          <th className="py-2 pr-3">Action</th>
          <th className="py-2 pr-3">Resource</th>
          <th className="py-2 pr-3">Metadata</th>
        </tr>
      </thead>
      <tbody>
        {data.map((r) => (
          <tr key={r.id} className="border-b border-gray-100 align-top">
            <td className="py-2 pr-3 font-mono text-gray-700">
              {formatTs(r.created_at)}
            </td>
            <td className="py-2 pr-3 font-mono text-gray-600">
              <code title={r.actor_sub}>{truncate(r.actor_sub, 16)}</code>
            </td>
            <td className="py-2 pr-3">
              <span className="rounded bg-gray-100 px-1.5 py-0.5 font-medium text-gray-700">
                {r.action}
              </span>
            </td>
            <td className="py-2 pr-3 text-gray-600">
              <span className="text-gray-500">{r.resource_type}</span>
              {r.resource_id ? (
                <>
                  <br />
                  <code className="text-[10px]">
                    {truncate(r.resource_id, 32)}
                  </code>
                </>
              ) : null}
            </td>
            <td className="py-2 pr-3">
              {Object.keys(r.metadata).length > 0 ? (
                <pre className="max-h-32 overflow-auto rounded bg-gray-50 p-1 font-mono text-[10px] text-gray-700">
                  {JSON.stringify(r.metadata, null, 2)}
                </pre>
              ) : (
                <span className="text-gray-400">—</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
