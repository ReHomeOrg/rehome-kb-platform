/**
 * /admin/tasks/[id] — admin_task status detail (#262, backend #238).
 *
 * staff_admin scope. Used после reindex / audit_log_export / eval_run
 * trigger для отслеживания progress + retrieve result_url.
 */

import { notFound } from "next/navigation";

import Nav from "@/app/_components/nav";
import { getAdminTask } from "@/lib/api/admin-tasks";
import { ApiError } from "@/lib/api/client";
import type { AdminTaskStatus, AdminTaskStatusView } from "@/lib/api/types";

interface PageProps {
  params: Promise<{ id: string }>;
}

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

export default async function AdminTaskDetailPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { id } = await params;

  let task: AdminTaskStatusView | undefined;
  let error: string | undefined;
  try {
    task = await getAdminTask(id);
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 404) {
        notFound();
      }
      if (e.status === 401 || e.status === 403) {
        error = "Доступ только для staff_admin.";
      } else {
        error = `Ошибка ${e.status}: ${e.message}`;
      }
    } else {
      error = "Не удалось загрузить task.";
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-3xl px-4 py-6">
        <a
          href="/admin"
          className="mb-3 inline-block text-xs text-blue-700 underline hover:text-blue-900"
        >
          ← Dashboard
        </a>
        <h1 className="mb-4 text-2xl font-semibold">Admin task</h1>

        {error !== undefined ? (
          <div
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900"
          >
            {error}
          </div>
        ) : null}

        {task ? (
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

            {task.status === "RUNNING" || task.status === "PENDING" ? (
              <p className="text-xs text-gray-500">
                Status может меняться — обновите страницу для актуальных
                данных. Auto-polling — backlog.
              </p>
            ) : null}
          </div>
        ) : null}
      </main>
    </>
  );
}
