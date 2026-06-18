/**
 * /admin/tasks/[id] — admin_task status detail (#262/backend #238).
 *
 * Client-side polling for RUNNING/PENDING (#263).
 */

import { notFound } from "next/navigation";

import Nav from "@/app/_components/nav";
import { getAdminTask } from "@/lib/api/admin-tasks";
import { ApiError } from "@/lib/api/client";
import type { AdminTaskStatusView } from "@/lib/api/types";

import TaskStatusCard from "./_components/task-status-card";

interface PageProps {
  params: Promise<{ id: string }>;
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
          className="mb-3 inline-block text-xs text-brand-strong underline hover:text-ink"
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

        {task ? <TaskStatusCard initial={task} /> : null}
      </main>
    </>
  );
}
