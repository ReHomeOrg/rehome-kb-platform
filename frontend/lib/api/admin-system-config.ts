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
