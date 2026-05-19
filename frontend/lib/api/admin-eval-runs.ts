/**
 * Admin eval-runs API client (#248, backend #244).
 *
 * Maps to `GET /api/v1/admin/llm/eval-runs`. staff_admin scope required.
 */

import { apiFetch } from "./client";
import type { EvalRunListResponse } from "./types";

export interface ListEvalRunsFilters {
  provider?: string;
  limit?: number;
}

export async function listEvalRuns(
  filters: ListEvalRunsFilters = {},
): Promise<EvalRunListResponse> {
  const params = new URLSearchParams();
  if (filters.provider) params.set("provider", filters.provider);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return apiFetch<EvalRunListResponse>(
    `/api/v1/admin/llm/eval-runs${qs ? `?${qs}` : ""}`,
  );
}
