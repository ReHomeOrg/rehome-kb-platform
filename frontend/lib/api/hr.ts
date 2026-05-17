/**
 * HR API methods (#153, PZ §7) — typed wrappers around `apiFetch`.
 *
 * Maps to backend `/api/v1/hr/employees/*` endpoints. Все endpoints
 * требуют HR_RESTRICTED scope (staff_hr / director).
 */

import { apiFetch } from "./client";
import type { HrEmployee, HrEmployeeListResponse } from "./types";

export interface ListEmployeesFilters {
  cursor?: string;
  limit?: number;
  include_terminated?: boolean;
}

export async function listEmployees(
  filters: ListEmployeesFilters = {},
): Promise<HrEmployeeListResponse> {
  const params = new URLSearchParams();
  if (filters.cursor) params.set("cursor", filters.cursor);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.include_terminated) {
    params.set("include_terminated", "true");
  }
  const qs = params.toString();
  return apiFetch<HrEmployeeListResponse>(
    `/api/v1/hr/employees${qs ? `?${qs}` : ""}`,
  );
}

export async function getEmployee(id: string): Promise<HrEmployee> {
  return apiFetch<HrEmployee>(`/api/v1/hr/employees/${encodeURIComponent(id)}`);
}

// ---------------------------------------------------------------------------
// Write side — HR_RESTRICTED. Mirror backend `HrEmployeeInput`/`HrEmployeePatch`.

export interface HrEmployeeCreateInput {
  user_id?: string | null;
  personnel_number?: string | null;
  full_name: string;
  position: string;
  department?: string | null;
  hire_date: string; // ISO date (YYYY-MM-DD)
  termination_date?: string | null;
  status?: "ACTIVE" | "ON_LEAVE" | "TERMINATED";
  contact_info?: Record<string, unknown>;
  notes?: Record<string, unknown>;
}

export type HrEmployeePatchInput = Partial<HrEmployeeCreateInput>;

export async function createEmployee(
  input: HrEmployeeCreateInput,
): Promise<HrEmployee> {
  return apiFetch<HrEmployee>("/api/v1/hr/employees", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export async function patchEmployee(
  id: string,
  input: HrEmployeePatchInput,
): Promise<HrEmployee> {
  return apiFetch<HrEmployee>(
    `/api/v1/hr/employees/${encodeURIComponent(id)}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function archiveEmployee(id: string): Promise<void> {
  await apiFetch<void>(`/api/v1/hr/employees/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}
