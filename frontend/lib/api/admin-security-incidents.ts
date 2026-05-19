/**
 * Admin security incidents API client (#249, backend #231).
 *
 * Maps to `GET /api/v1/admin/security-incidents`. staff_admin scope
 * required (ФЗ-152 §17.1).
 */

import { apiFetch } from "./client";
import type {
  IncidentSeverity,
  IncidentStatus,
  SecurityIncidentsListResponse,
} from "./types";

export interface ListSecurityIncidentsFilters {
  severity?: IncidentSeverity;
  status?: IncidentStatus;
  cursor?: string;
}

export async function listSecurityIncidents(
  filters: ListSecurityIncidentsFilters = {},
): Promise<SecurityIncidentsListResponse> {
  const params = new URLSearchParams();
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.status) params.set("status", filters.status);
  if (filters.cursor) params.set("cursor", filters.cursor);
  const qs = params.toString();
  return apiFetch<SecurityIncidentsListResponse>(
    `/api/v1/admin/security-incidents${qs ? `?${qs}` : ""}`,
  );
}
