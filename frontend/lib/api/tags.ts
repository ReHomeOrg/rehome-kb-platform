/**
 * Tags API methods (UI.1 #75) — typed wrappers.
 *
 * Maps to backend `/api/v1/tags` (E2.6 #52).
 */

import { apiFetch } from "./client";
import type { TagsListResponse } from "./types";

export interface ListTagsFilters {
  q?: string;
  limit?: number;
}

export async function listTags(
  filters: ListTagsFilters = {},
): Promise<TagsListResponse> {
  const params = new URLSearchParams();
  if (filters.q) params.set("q", filters.q);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return apiFetch<TagsListResponse>(`/api/v1/tags${qs ? `?${qs}` : ""}`);
}
