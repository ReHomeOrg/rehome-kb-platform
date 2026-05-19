/**
 * Admin stats API client (#251, backend #227).
 *
 * Maps to `GET /api/v1/admin/stats`. staff_admin / staff_legal scope.
 */

import { apiFetch } from "./client";
import type { AdminStats } from "./types";

export interface GetAdminStatsFilters {
  from?: string;
  to?: string;
}

export async function getAdminStats(
  filters: GetAdminStatsFilters = {},
): Promise<AdminStats> {
  const params = new URLSearchParams();
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  const qs = params.toString();
  return apiFetch<AdminStats>(`/api/v1/admin/stats${qs ? `?${qs}` : ""}`);
}
