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
      <p
        role="status"
        className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600"
      >
        Записей не найдено по заданным фильтрам.
      </p>
    );
  }
  return (
    <table
      className="w-full table-auto border-collapse text-xs"
      aria-label="Audit log records"
    >
      <caption className="sr-only">
        Audit log: time, actor, action, resource, metadata
      </caption>
      <thead>
        <tr className="border-b border-gray-300 text-left uppercase text-gray-500">
          <th scope="col" className="py-2 pr-3">
            Время
          </th>
          <th scope="col" className="py-2 pr-3">
            Actor
          </th>
          <th scope="col" className="py-2 pr-3">
            Action
          </th>
          <th scope="col" className="py-2 pr-3">
            Resource
          </th>
          <th scope="col" className="py-2 pr-3">
            Metadata
          </th>
        </tr>
      </thead>
      <tbody>
        {data.map((r) => (
          <tr key={r.id} className="border-b border-gray-100 align-top">
            <td className="py-2 pr-3 font-mono text-gray-700">
              <time dateTime={r.created_at}>{formatTs(r.created_at)}</time>
            </td>
            <td className="py-2 pr-3 font-mono text-gray-600">
              <code title={r.actor_sub} aria-label={`Actor ${r.actor_sub}`}>
                {truncate(r.actor_sub, 16)}
              </code>
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
                  <code
                    className="text-[10px]"
                    aria-label={`Resource id ${r.resource_id}`}
                  >
                    {truncate(r.resource_id, 32)}
                  </code>
                </>
              ) : null}
            </td>
            <td className="py-2 pr-3">
              {Object.keys(r.metadata).length > 0 ? (
                <pre
                  className="max-h-32 overflow-auto rounded bg-gray-50 p-1 font-mono text-[10px] text-gray-700"
                  aria-label="Metadata JSON"
                >
                  {JSON.stringify(r.metadata, null, 2)}
                </pre>
              ) : (
                <span aria-label="metadata empty" className="text-gray-400">
                  —
                </span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
