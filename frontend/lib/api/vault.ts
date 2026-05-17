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
