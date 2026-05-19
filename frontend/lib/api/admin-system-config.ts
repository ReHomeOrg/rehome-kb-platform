/**
 * Admin system-config API client (#252, backend #229).
 *
 * Maps to `GET /api/v1/admin/system-config`. staff_admin scope.
 * PATCH endpoint — backlog (ADR-0019).
 */

import { apiFetch } from "./client";
import type { SystemConfig } from "./types";

export async function getSystemConfig(): Promise<SystemConfig> {
  return apiFetch<SystemConfig>("/api/v1/admin/system-config");
}

// PATCH /admin/system-config (#266). Allow-listed keys per ADR-0019;
// unknown keys → 422 от backend. Caller передаёт flat-key dict.
export type SystemConfigPatch = Record<string, unknown>;

export async function patchSystemConfig(
  updates: SystemConfigPatch,
  mfaToken?: string,
): Promise<SystemConfig> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (mfaToken) headers["X-MFA-Token"] = mfaToken;
  return apiFetch<SystemConfig>("/api/v1/admin/system-config", {
    method: "PATCH",
    body: JSON.stringify(updates),
    headers,
  });
}
