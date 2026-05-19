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

export interface SetActiveLlmProviderInput {
  provider_id: string;
  reason?: string;
}

export interface SetActiveLlmProviderResult {
  active_provider: string;
}

export async function setActiveLlmProvider(
  input: SetActiveLlmProviderInput,
  mfaToken?: string,
): Promise<SetActiveLlmProviderResult> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (mfaToken) headers["X-MFA-Token"] = mfaToken;
  return apiFetch<SetActiveLlmProviderResult>("/api/v1/admin/llm/active", {
    method: "PUT",
    body: JSON.stringify(input),
    headers,
  });
}
