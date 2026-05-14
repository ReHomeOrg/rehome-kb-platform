/**
 * Premises API methods (#160, PZ §5) — typed wrappers around `apiFetch`.
 *
 * Maps to backend `/api/v1/premises-cards/*` endpoints (#142 read, #148
 * write, #154 search). Read endpoints поддерживают anonymous access
 * (identification subset видим всем); detail endpoint per-scope
 * projection.
 */

import { apiFetch } from "./client";
import type {
  PremisesListResponse,
  PremisesSearchResponse,
  PremisesView,
} from "./types";

export interface ListPremisesFilters {
  cursor?: string;
  limit?: number;
}

export async function listPremises(
  filters: ListPremisesFilters = {},
): Promise<PremisesListResponse> {
  const params = new URLSearchParams();
  if (filters.cursor) params.set("cursor", filters.cursor);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return apiFetch<PremisesListResponse>(
    `/api/v1/premises-cards${qs ? `?${qs}` : ""}`,
  );
}

export async function getPremisesCard(slug: string): Promise<PremisesView> {
  return apiFetch<PremisesView>(
    `/api/v1/premises-cards/${encodeURIComponent(slug)}`,
  );
}

export interface SearchPremisesInput {
  q: string;
  limit?: number;
}

export async function searchPremises(
  input: SearchPremisesInput,
): Promise<PremisesSearchResponse> {
  return apiFetch<PremisesSearchResponse>("/api/v1/premises-cards/search", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}
