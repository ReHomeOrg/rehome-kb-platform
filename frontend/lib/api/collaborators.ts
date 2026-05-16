/**
 * Collaborators API methods (ADR-0014, ТЗ §10) — typed wrappers.
 *
 * Maps на backend `/api/v1/collaborators/*` endpoints (PRs #231-234,
 * Slice 1+2). 7 endpoints — CRUD + lifecycle (activate/suspend).
 *
 * Видимость per scope (ADR-0014 §3): guest/LOGGED → только D-группа;
 * STAFF+ → все группы. Поля per scope (Public/Internal/Admin) —
 * backend выбирает variant; frontend trust'ит TypeScript union.
 */

import { apiFetch } from "./client";
import type {
  CollaboratorAdmin,
  CollaboratorFinancialGroup,
  CollaboratorInternal,
  CollaboratorPublic,
  CollaboratorStatus,
  CollaboratorType,
  CollaboratorsListResponse,
} from "./types";

export interface ListCollaboratorsFilters {
  type?: CollaboratorType;
  status?: CollaboratorStatus;
  service_area?: string;
  cursor?: string;
  limit?: number;
}

export async function listCollaborators(
  filters: ListCollaboratorsFilters = {},
): Promise<CollaboratorsListResponse> {
  const params = new URLSearchParams();
  if (filters.type) params.set("type", filters.type);
  if (filters.status) params.set("status", filters.status);
  if (filters.service_area) params.set("service_area", filters.service_area);
  if (filters.cursor) params.set("cursor", filters.cursor);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return apiFetch<CollaboratorsListResponse>(
    `/api/v1/collaborators${qs ? `?${qs}` : ""}`,
  );
}

/**
 * Detail per scope: возвращает Public/Internal/Admin в зависимости от
 * прав пользователя. Caller'ам с STAFF scope — это Internal или Admin.
 */
export async function getCollaborator(
  id: string,
): Promise<CollaboratorPublic | CollaboratorInternal | CollaboratorAdmin> {
  return apiFetch<CollaboratorPublic | CollaboratorInternal | CollaboratorAdmin>(
    `/api/v1/collaborators/${encodeURIComponent(id)}`,
  );
}

// ---------------------------------------------------------------------------
// Write side — STAFF+ only.

export interface CollaboratorCreateInput {
  name: string;
  brand_name?: string | null;
  type: CollaboratorType;
  financial_group?: CollaboratorFinancialGroup | null;
  status?: CollaboratorStatus;
  legal_entity_type?: string | null;
  inn?: string | null;
  ogrn?: string | null;
  kpp?: string | null;
  service_area: string;
  working_hours?: string | null;
  website?: string | null;
  responsible_internal?: string | null;
  contract_document_id?: string | null;
  fallback_collaborator_id?: string | null;
  contacts?: Array<Record<string, unknown>>;
  financial_terms?: Record<string, unknown>;
  api_integration?: Record<string, unknown>;
  sla?: Record<string, unknown>;
  counterparty_check?: Record<string, unknown>;
}

export async function createCollaborator(
  input: CollaboratorCreateInput,
): Promise<CollaboratorInternal | CollaboratorAdmin> {
  return apiFetch<CollaboratorInternal | CollaboratorAdmin>(
    "/api/v1/collaborators",
    {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export type CollaboratorPatchInput = Partial<CollaboratorCreateInput>;

export async function patchCollaborator(
  id: string,
  input: CollaboratorPatchInput,
): Promise<CollaboratorInternal | CollaboratorAdmin> {
  return apiFetch<CollaboratorInternal | CollaboratorAdmin>(
    `/api/v1/collaborators/${encodeURIComponent(id)}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function archiveCollaborator(id: string): Promise<void> {
  await apiFetch<void>(`/api/v1/collaborators/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function activateCollaborator(
  id: string,
): Promise<CollaboratorInternal | CollaboratorAdmin> {
  return apiFetch<CollaboratorInternal | CollaboratorAdmin>(
    `/api/v1/collaborators/${encodeURIComponent(id)}/activate`,
    { method: "POST" },
  );
}

export interface SuspendInput {
  reason: string;
  until?: string | null;
}

export async function suspendCollaborator(
  id: string,
  input: SuspendInput,
): Promise<CollaboratorInternal | CollaboratorAdmin> {
  return apiFetch<CollaboratorInternal | CollaboratorAdmin>(
    `/api/v1/collaborators/${encodeURIComponent(id)}/suspend`,
    {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    },
  );
}
