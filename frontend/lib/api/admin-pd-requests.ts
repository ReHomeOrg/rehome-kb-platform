/**
 * Admin personal-data requests API client (#250, backend #232).
 *
 * Maps to `GET /api/v1/admin/personal-data/requests`. staff_admin
 * scope (ФЗ-152 §15 SAR).
 */

import { apiFetch } from "./client";
import type {
  PdRequestStatus,
  PdRequestType,
  PersonalDataRequestsListResponse,
} from "./types";

export interface ListPdRequestsFilters {
  status?: PdRequestStatus;
  type?: PdRequestType;
  cursor?: string;
}

export async function listPdRequests(
  filters: ListPdRequestsFilters = {},
): Promise<PersonalDataRequestsListResponse> {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.type) params.set("type", filters.type);
  if (filters.cursor) params.set("cursor", filters.cursor);
  const qs = params.toString();
  return apiFetch<PersonalDataRequestsListResponse>(
    `/api/v1/admin/personal-data/requests${qs ? `?${qs}` : ""}`,
  );
}
