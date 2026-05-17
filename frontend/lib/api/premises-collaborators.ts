/**
 * Premises ↔ Collaborators junction API (ТЗ §10.6, Slice 5).
 *
 * Backend endpoints в `backend/src/api/collaborators/junction_router.py`:
 * - GET /api/v1/premises/{id}/collaborators — scope-aware list
 * - POST same — assign (STAFF+); body { collaborator_id, role, priority?, notes? }
 * - DELETE /api/v1/premises/{id}/collaborators/{collaborator_id}?role=...
 */

import { apiFetch } from "./client";
import type { PremisesCollaboratorsListResponse } from "./types";

export async function listPremisesCollaborators(
  premisesId: string,
): Promise<PremisesCollaboratorsListResponse> {
  return apiFetch<PremisesCollaboratorsListResponse>(
    `/api/v1/premises/${encodeURIComponent(premisesId)}/collaborators`,
  );
}

export interface AssignCollaboratorInput {
  collaborator_id: string;
  role: string;
  priority?: number;
  notes?: string | null;
}

export async function assignCollaborator(
  premisesId: string,
  input: AssignCollaboratorInput,
): Promise<void> {
  await apiFetch<void>(
    `/api/v1/premises/${encodeURIComponent(premisesId)}/collaborators`,
    {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function removeCollaborator(
  premisesId: string,
  collaboratorId: string,
  role?: string,
): Promise<void> {
  const qs = role ? `?role=${encodeURIComponent(role)}` : "";
  await apiFetch<void>(
    `/api/v1/premises/${encodeURIComponent(premisesId)}/collaborators/${encodeURIComponent(collaboratorId)}${qs}`,
    { method: "DELETE" },
  );
}
