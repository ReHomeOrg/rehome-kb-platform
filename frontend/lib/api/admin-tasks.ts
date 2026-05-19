/**
 * Admin tasks API client (#262, backend #238).
 *
 * Maps to `GET /api/v1/admin/tasks/{id}`. Universal task status
 * lookup для reindex / audit_log_export / eval_run.
 */

import { apiFetch } from "./client";
import type { AdminTaskStatusView } from "./types";

export async function getAdminTask(id: string): Promise<AdminTaskStatusView> {
  return apiFetch<AdminTaskStatusView>(
    `/api/v1/admin/tasks/${encodeURIComponent(id)}`,
  );
}
