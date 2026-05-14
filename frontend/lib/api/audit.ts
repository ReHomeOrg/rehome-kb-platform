/**
 * Audit log API client (#166, backend #161).
 *
 * Maps to backend `GET /api/v1/audit-log`. LEGAL access tier required
 * (staff_admin / director / legal); non-LEGAL → 403.
 */

import { apiFetch } from "./client";
import type { AuditListResponse } from "./types";

export interface AuditFilters {
  actor_sub?: string;
  resource_type?: string;
  resource_id?: string;
  action?: string;
  since?: string; // ISO 8601
  until?: string;
  limit?: number;
  offset?: number;
}

export async function listAudit(
  filters: AuditFilters = {},
): Promise<AuditListResponse> {
  const params = new URLSearchParams();
  if (filters.actor_sub) params.set("actor_sub", filters.actor_sub);
  if (filters.resource_type) params.set("resource_type", filters.resource_type);
  if (filters.resource_id) params.set("resource_id", filters.resource_id);
  if (filters.action) params.set("action", filters.action);
  if (filters.since) params.set("since", filters.since);
  if (filters.until) params.set("until", filters.until);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  const qs = params.toString();
  return apiFetch<AuditListResponse>(`/api/v1/audit-log${qs ? `?${qs}` : ""}`);
}
