/**
 * Admin KB users API client (#253, backend #230).
 *
 * Maps to `GET /api/v1/admin/users`. staff_admin scope.
 */

import { apiFetch } from "./client";
import type {
  KbUser,
  KbUserRole,
  KbUserStatus,
  KbUsersListResponse,
} from "./types";

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

export async function getKbUser(id: string): Promise<KbUser> {
  return apiFetch<KbUser>(`/api/v1/admin/users/${encodeURIComponent(id)}`);
}

export interface KbUserCreateInput {
  email: string;
  full_name: string;
  role: KbUserRole;
  permissions?: string[];
}

export async function createKbUser(input: KbUserCreateInput): Promise<KbUser> {
  return apiFetch<KbUser>("/api/v1/admin/users", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export interface KbUserPatchInput {
  role?: KbUserRole;
  status?: KbUserStatus;
  permissions?: string[];
}

export async function patchKbUser(
  id: string,
  input: KbUserPatchInput,
): Promise<KbUser> {
  return apiFetch<KbUser>(`/api/v1/admin/users/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export async function deactivateKbUser(id: string): Promise<void> {
  await apiFetch<void>(`/api/v1/admin/users/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}
