/**
 * Webhooks API methods (UI.7 #95) — typed wrappers.
 *
 * Maps to backend `/api/v1/webhooks` (E5.1/E5.2 #87/#89).
 */

import { apiFetch } from "./client";
import type {
  Webhook,
  WebhookInput,
  WebhookTestResponse,
  WebhooksListResponse,
} from "./types";

export async function listWebhooks(): Promise<WebhooksListResponse> {
  return apiFetch<WebhooksListResponse>("/api/v1/webhooks");
}

export async function createWebhook(input: WebhookInput): Promise<Webhook> {
  return apiFetch<Webhook>("/api/v1/webhooks", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function deleteWebhook(id: string): Promise<void> {
  await apiFetch<void>(`/api/v1/webhooks/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export async function testWebhook(id: string): Promise<WebhookTestResponse> {
  return apiFetch<WebhookTestResponse>(
    `/api/v1/webhooks/${encodeURIComponent(id)}/test`,
    { method: "POST" },
  );
}
