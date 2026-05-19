/**
 * Admin KB users API client (#253, backend #230).
 *
 * Maps to `GET /api/v1/admin/users`. staff_admin scope.
 */

import { apiFetch } from "./client";
import type { KbUserRole, KbUserStatus, KbUsersListResponse } from "./types";

export interface ListKbUsersFilters {
  role?: KbUserRole;
  status?: KbUserStatus;
  cursor?: string;
}

export async function listKbUsers(
  filters: ListKbUsersFilters = {},
): Promise<KbUsersListResponse> {
  const params = new URLSearchParams();
  if (filters.role) params.set("role", filters.role);
  if (filters.status) params.set("status", filters.status);
  if (filters.cursor) params.set("cursor", filters.cursor);
  const qs = params.toString();
  return apiFetch<KbUsersListResponse>(
    `/api/v1/admin/users${qs ? `?${qs}` : ""}`,
  );
}
