"use client";

/**
 * Task status card с auto-polling (#263). Client component:
 * - Receives initial state из SSR.
 * - Polls GET /admin/tasks/{id} every 3 sec пока status ∈ {PENDING, RUNNING}.
 * - Stops on terminal (COMPLETED/FAILED/CANCELLED) или unmount.
 */

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api/client";
import { getAdminTask } from "@/lib/api/admin-tasks";
import type { AdminTaskStatus, AdminTaskStatusView } from "@/lib/api/types";

interface Props {
  initial: AdminTaskStatusView;
}

const POLL_INTERVAL_MS = 3000;
const TERMINAL: ReadonlySet<AdminTaskStatus> = new Set<AdminTaskStatus>([
  "COMPLETED",
  "FAILED",
  "CANCELLED",
]);

function statusBadge(status: AdminTaskStatus): JSX.Element {
  const colors: Record<AdminTaskStatus, string> = {
    PENDING: "bg-blue-100 text-blue-800",
    RUNNING: "bg-indigo-100 text-indigo-800",
    COMPLETED: "bg-green-100 text-green-800",
    FAILED: "bg-red-100 text-red-800",
    CANCELLED: "bg-gray-100 text-gray-700",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[status]}`}
    >
      {status}
    </span>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", { hour12: false });
}

export default function TaskStatusCard({ initial }: Props): JSX.Element {
  const [task, setTask] = useState<AdminTaskStatusView>(initial);
  const [polling, setPolling] = useState(!TERMINAL.has(initial.status));
  const [pollError, setPollError] = useState<string | undefined>();

  useEffect(() => {
    if (TERMINAL.has(task.status)) {
      setPolling(false);
      return;
    }
    setPolling(true);
    const id = setInterval(() => {
      void (async () => {
        try {
          const next = await getAdminTask(task.task_id);
          setTask(next);
          setPollError(undefined);
        } catch (e) {
          if (e instanceof ApiError) {
            setPollError(`Polling error ${e.status}: ${e.message}`);
          } else {
            setPollError("Polling failed");
          }
        }
      })();
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [task.status, task.task_id]);

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-gray-200 bg-white p-4">
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <dt className="text-gray-600">Task ID</dt>
          <dd className="font-mono">{task.task_id}</dd>
          <dt className="text-gray-600">Type</dt>
          <dd className="font-mono">{task.type}</dd>
          <dt className="text-gray-600">Status</dt>
          <dd>{statusBadge(task.status)}</dd>
          <dt className="text-gray-600">Progress</dt>
          <dd>{task.progress_percent}%</dd>
          <dt className="text-gray-600">Создана</dt>
          <dd>{formatDate(task.created_at)}</dd>
          <dt className="text-gray-600">Завершена</dt>
          <dd>{formatDate(task.completed_at)}</dd>
          {task.result_url ? (
            <>
              <dt className="text-gray-600">Result URL</dt>
              <dd>
                <a
                  href={task.result_url}
                  className="break-all text-blue-700 underline hover:text-blue-900"
                >
                  {task.result_url}
                </a>
              </dd>
            </>
          ) : null}
          {task.error ? (
            <>
              <dt className="text-gray-600">Error</dt>
              <dd className="text-red-700">{task.error}</dd>
            </>
          ) : null}
        </dl>
      </div>

      {polling ? (
        <p
          className="text-xs text-gray-500"
          aria-live="polite"
          aria-label="Polling status"
        >
          Auto-polling каждые 3s (status: {task.status})…
        </p>
      ) : (
        <p className="text-xs text-gray-500">
          Polling завершён (terminal status: {task.status}).
        </p>
      )}

      {pollError ? (
        <div
          role="alert"
          className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900"
        >
          {pollError} — последний known status сохранён.
        </div>
      ) : null}
    </div>
  );
}
