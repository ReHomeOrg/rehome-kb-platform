/**
 * kb-vault API client (ADR-0011, ADR-0016, Slice 1).
 *
 * Endpoints mirror `backend/src/api/vault/router.py`. Все crypto-blob'ы
 * передаются как base64. Backend zero-knowledge — никакая интерпретация
 * на сервере.
 */

import { apiFetch } from "./client";

export interface VaultMeView {
  is_setup: boolean;
  argon_salt_b64: string | null;
  x25519_pubkey_b64: string | null;
  encrypted_x25519_privkey_b64: string | null;
  has_totp: boolean;
  last_unlock_at: string | null;
}

export interface VaultSetupInput {
  argon_salt_b64: string;
  auth_hash_b64: string;
  encrypted_x25519_privkey_b64: string;
  x25519_pubkey_b64: string;
}

export interface VaultUnlockInput {
  auth_hash_b64: string;
}

export interface VaultUnlockResponse {
  success: boolean;
}

export async function getVaultMe(): Promise<VaultMeView> {
  return apiFetch<VaultMeView>("/api/v1/vault/me");
}

/** /whoami возвращает Keycloak sub — нужен для self-wrap в create_secret. */
export async function getCurrentUserId(): Promise<string> {
  const resp = await apiFetch<{ sub: string }>("/api/v1/whoami");
  return resp.sub;
}

export async function setupVault(input: VaultSetupInput): Promise<VaultMeView> {
  return apiFetch<VaultMeView>("/api/v1/vault/setup", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export async function unlockVault(
  input: VaultUnlockInput,
): Promise<VaultUnlockResponse> {
  return apiFetch<VaultUnlockResponse>("/api/v1/vault/unlock", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Secrets — все блобы передаются base64-encoded. Backend zero-knowledge.

export interface VaultSecretWrapInput {
  /** EXACTLY ONE из (user_id, group_id) указан. */
  user_id?: string | null;
  group_id?: string | null;
  wrapped_key_b64: string;
}

export interface VaultSecretCreateInput {
  title_ciphertext_b64: string;
  category: string;
  blob_ciphertext_b64: string;
  /** Минимум 1; для Slice 2 (personal) — всегда self-wrap [{user_id, wrapped_key}]. */
  wraps: VaultSecretWrapInput[];
  expires_at?: string | null;
}

export interface VaultSecretUpdateInput {
  blob_ciphertext_b64: string;
  /** Last seen payload_version. Backend 409 если не совпадает. */
  expected_version: number;
}

export interface VaultSecretMetadataView {
  id: string;
  title_ciphertext_b64: string;
  category: string;
  owner_id: string;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
  archived_at: string | null;
}

export interface VaultSecretView extends VaultSecretMetadataView {
  blob_ciphertext_b64: string;
  payload_version: number;
  wrapped_key_b64: string;
  via_group_id: string | null;
}

export interface VaultSecretListResponse {
  data: VaultSecretMetadataView[];
}

export async function listVaultSecrets(): Promise<VaultSecretListResponse> {
  return apiFetch<VaultSecretListResponse>("/api/v1/vault/secrets");
}

export async function getVaultSecret(id: string): Promise<VaultSecretView> {
  return apiFetch<VaultSecretView>(
    `/api/v1/vault/secrets/${encodeURIComponent(id)}`,
  );
}

export async function createVaultSecret(
  input: VaultSecretCreateInput,
): Promise<VaultSecretView> {
  return apiFetch<VaultSecretView>("/api/v1/vault/secrets", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export async function updateVaultSecret(
  id: string,
  input: VaultSecretUpdateInput,
): Promise<VaultSecretView> {
  return apiFetch<VaultSecretView>(
    `/api/v1/vault/secrets/${encodeURIComponent(id)}`,
    {
      method: "PUT",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function deleteVaultSecret(id: string): Promise<void> {
  await apiFetch<void>(`/api/v1/vault/secrets/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}
