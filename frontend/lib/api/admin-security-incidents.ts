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
  SecurityIncident,
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

export async function getSecurityIncident(
  id: string,
): Promise<SecurityIncident> {
  return apiFetch<SecurityIncident>(
    `/api/v1/admin/security-incidents/${encodeURIComponent(id)}`,
  );
}

export interface SecurityIncidentPatchInput {
  status?: IncidentStatus;
  resolution_note?: string | null;
  rkn_notified_at?: string | null;
}

export async function patchSecurityIncident(
  id: string,
  input: SecurityIncidentPatchInput,
): Promise<SecurityIncident> {
  return apiFetch<SecurityIncident>(
    `/api/v1/admin/security-incidents/${encodeURIComponent(id)}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    },
  );
}
