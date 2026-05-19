/**
 * Admin maintenance API client (#259).
 *
 * POST /admin/reindex (backend #238/#240): creates admin_task,
 * returns task_id. articles scope — real reindex; others — honest stub.
 *
 * DELETE /admin/cache (backend #238): honest stub (no cache layer);
 * returns 202 + audit log.
 */

import { apiFetch } from "./client";

export type ReindexScope = "all" | "articles" | "documents" | "premises_cards";
export type CacheScope =
  | "all"
  | "articles"
  | "documents"
  | "premises_cards"
  | "search";

export interface TriggerReindexResponse {
  task_id: string;
}

export async function triggerReindex(
  scope: ReindexScope = "all",
): Promise<TriggerReindexResponse> {
  return apiFetch<TriggerReindexResponse>("/api/v1/admin/reindex", {
    method: "POST",
    body: JSON.stringify({ scope }),
    headers: { "Content-Type": "application/json" },
  });
}

export interface InvalidateCacheResponse {
  status: string;
  scope: string;
}

export async function invalidateCache(
  scope: CacheScope = "all",
): Promise<InvalidateCacheResponse> {
  return apiFetch<InvalidateCacheResponse>(
    `/api/v1/admin/cache?scope=${encodeURIComponent(scope)}`,
    { method: "DELETE" },
  );
}
