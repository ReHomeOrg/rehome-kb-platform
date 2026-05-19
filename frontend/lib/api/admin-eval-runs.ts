/**
 * Admin eval-runs API client (#248, backend #244).
 *
 * Maps to `GET /api/v1/admin/llm/eval-runs`. staff_admin scope required.
 */

import { apiFetch } from "./client";
import type { EvalRunListResponse, EvalTestSet } from "./types";

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

// POST /admin/llm/eval-runs (backend #244). MVP: providers=["mock"]
// + test_set="smoke" only; backend reject'нет 422 для других.
export interface StartEvalRunInput {
  providers: string[];
  test_set: EvalTestSet;
  custom_questions?: string[];
}

export interface StartEvalRunResponse {
  run_id: string;
}

export async function startEvalRun(
  input: StartEvalRunInput,
): Promise<StartEvalRunResponse> {
  return apiFetch<StartEvalRunResponse>("/api/v1/admin/llm/eval-runs", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}
