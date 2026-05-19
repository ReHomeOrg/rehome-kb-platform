/**
 * Admin audit-log export API client (#261, backend #239).
 *
 * POST /admin/audit-log/export — sync execution, returns task_id с
 * result_url указывающим на existing /audit-log/export.csv.
 */

import { apiFetch } from "./client";

export type AuditExportFormat = "csv" | "json";

export interface AuditExportInput {
  from: string;
  to: string;
  filters?: Record<string, string>;
  format?: AuditExportFormat;
  reason?: string;
}

export interface AuditExportResponse {
  task_id: string;
  estimated_ready_at: string | null;
}

export async function startAuditExport(
  input: AuditExportInput,
): Promise<AuditExportResponse> {
  return apiFetch<AuditExportResponse>("/api/v1/admin/audit-log/export", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}
