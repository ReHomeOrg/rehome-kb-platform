/**
 * Admin LLM providers API client (#252, backend #228).
 *
 * Maps to `GET /api/v1/admin/llm/providers`. staff_admin scope.
 */

import { apiFetch } from "./client";
import type { LlmProvidersListResponse } from "./types";

export async function listLlmProviders(): Promise<LlmProvidersListResponse> {
  return apiFetch<LlmProvidersListResponse>("/api/v1/admin/llm/providers");
}
