/**
 * Eval-runs table — per-run row + nested provider results (#248).
 */

import type { EvalRunSummary } from "@/lib/api/types";

interface Props {
  runs: EvalRunSummary[];
  error?: string | undefined;
}

function formatPercent(v: number | null): string {
  if (v === null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function formatLatency(v: number | null): string {
  if (v === null) return "—";
  return `${v} ms`;
}

function formatCost(v: number | null): string {
  if (v === null) return "—";
  if (v === 0) return "0";
  return `₽${v.toFixed(4)}`;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ru-RU", { hour12: false });
}

function statusBadge(status: EvalRunSummary["status"]): JSX.Element {
  const colors: Record<EvalRunSummary["status"], string> = {
    RUNNING: "bg-blue-100 text-blue-800",
    COMPLETED: "bg-green-100 text-green-800",
    FAILED: "bg-red-100 text-red-800",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[status]}`}
      aria-label={`Status ${status}`}
    >
      {status}
    </span>
  );
}

export default function EvalRunsTable({ runs, error }: Props): JSX.Element {
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
  if (runs.length === 0) {
    return (
      <div className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Нет прогонов. Запустите через `POST /admin/llm/eval-runs` (backend
        #244).
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {runs.map((run) => (
        <div
          key={run.id}
          className="rounded-md border border-gray-200 bg-white shadow-sm"
        >
          <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 px-4 py-2 text-xs">
            <div className="flex items-center gap-3">
              <code className="font-mono text-gray-500">{run.id.slice(0, 8)}</code>
              {statusBadge(run.status)}
              <span className="text-gray-700">
                providers: {run.providers.join(", ") || "—"}
              </span>
              <span className="text-gray-700">test_set: {run.test_set ?? "—"}</span>
            </div>
            <div className="text-gray-500">
              {formatDateTime(run.started_at)}
              {run.completed_at ? ` → ${formatDateTime(run.completed_at)}` : ""}
            </div>
          </header>
          {run.results.length > 0 ? (
            <table className="w-full table-fixed text-xs">
              <thead className="bg-gray-50 text-left text-gray-600">
                <tr>
                  <th className="px-3 py-2">Provider</th>
                  <th className="px-3 py-2">Composite</th>
                  <th className="px-3 py-2">Correctness</th>
                  <th className="px-3 py-2">Faithfulness</th>
                  <th className="px-3 py-2">Citations</th>
                  <th className="px-3 py-2">Refusal</th>
                  <th className="px-3 py-2">Latency</th>
                  <th className="px-3 py-2">Cost / query</th>
                </tr>
              </thead>
              <tbody>
                {run.results.map((r) => (
                  <tr key={`${run.id}-${r.provider}`} className="border-t border-gray-100">
                    <td className="px-3 py-2 font-mono">{r.provider}</td>
                    <td className="px-3 py-2">{formatPercent(r.composite_score)}</td>
                    <td className="px-3 py-2">{formatPercent(r.answer_correctness)}</td>
                    <td className="px-3 py-2">{formatPercent(r.faithfulness)}</td>
                    <td className="px-3 py-2">{formatPercent(r.citation_accuracy)}</td>
                    <td className="px-3 py-2">{formatPercent(r.refusal_correctness)}</td>
                    <td className="px-3 py-2">{formatLatency(r.avg_latency_ms)}</td>
                    <td className="px-3 py-2">{formatCost(r.cost_per_query_rub)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="px-4 py-3 text-xs text-gray-500">
              Результаты ещё не сохранены (run в процессе или failed).
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
