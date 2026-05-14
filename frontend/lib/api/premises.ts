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

// ---------------------------------------------------------------------------
// Write side (#162) — staff_admin only.

export interface PremisesCreateInput {
  slug: string;
  address: string;
  status?: "DRAFT" | "PUBLISHED" | "RENTED" | "ARCHIVED";
  internal_code?: string | null;
  postal_code?: string | null;
  cadastral_number?: string | null;
  premises_uuid?: string | null;
  owner?: Record<string, unknown>;
  owner_representative?: Record<string, unknown> | null;
  current_tenant?: Record<string, unknown> | null;
  financial_data?: Record<string, unknown>;
  tenant_info?: Record<string, unknown>;
  internal_data?: Record<string, unknown>;
  extra_identification?: Record<string, unknown>;
}

export async function createPremisesCard(
  input: PremisesCreateInput,
): Promise<PremisesView> {
  return apiFetch<PremisesView>("/api/v1/premises-cards", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export type PremisesPatchInput = Partial<Omit<PremisesCreateInput, "slug">>;

export async function patchPremisesCard(
  slug: string,
  input: PremisesPatchInput,
): Promise<PremisesView> {
  return apiFetch<PremisesView>(
    `/api/v1/premises-cards/${encodeURIComponent(slug)}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function archivePremisesCard(slug: string): Promise<void> {
  await apiFetch<void>(
    `/api/v1/premises-cards/${encodeURIComponent(slug)}`,
    { method: "DELETE" },
  );
}
