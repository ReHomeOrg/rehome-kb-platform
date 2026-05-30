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
  /** Ciphertext под vaultKey, decrypt'ится клиентом для TOTP verify. */
  totp_secret_encrypted_b64: string | null;
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

/**
 * ADR-0017 §E rotation — atomic re-wrap для true revoke. Client decrypt'ит
 * blob с old secret_key, generate new secret_key, re-encrypt blob, re-wrap
 * для surviving recipients (revoked user'а — не включён в new_wraps).
 */
export interface VaultSecretRotateInput {
  /** Title re-encrypted с новым secret_key. Обязательно — без него title undecryptable. */
  new_title_ciphertext_b64: string;
  new_blob_ciphertext_b64: string;
  expected_version: number;
  new_wraps: VaultSecretWrapInput[];
}

/** Owner-facing wrap metadata — БЕЗ `wrapped_key` (zero-knowledge property). */
export interface VaultSecretWrapView {
  user_id: string;
  group_id: string | null;
}

export interface VaultSecretWrapListResponse {
  data: VaultSecretWrapView[];
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

// ---------------------------------------------------------------------------
// Groups (ADR-0016 Slice 3 — management only; secret sharing flow требует
// backend additions: group keypair + pubkey discovery + add-wrap endpoint).

export interface VaultGroupView {
  id: string;
  name: string;
  description: string | null;
  created_by: string;
  created_at: string;
}

export interface VaultGroupCreateInput {
  name: string;
  description?: string | null;
}

export interface VaultGroupListResponse {
  data: VaultGroupView[];
}

export interface VaultGroupMemberView {
  group_id: string;
  user_id: string;
  role: "owner" | "member";
  added_at: string;
}

export interface VaultGroupMemberAddInput {
  user_id: string;
  role?: "owner" | "member";
}

export interface VaultGroupMemberListResponse {
  data: VaultGroupMemberView[];
}

export async function listVaultGroups(): Promise<VaultGroupListResponse> {
  return apiFetch<VaultGroupListResponse>("/api/v1/vault/groups");
}

export async function createVaultGroup(
  input: VaultGroupCreateInput,
): Promise<VaultGroupView> {
  return apiFetch<VaultGroupView>("/api/v1/vault/groups", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export async function listGroupMembers(
  groupId: string,
): Promise<VaultGroupMemberListResponse> {
  return apiFetch<VaultGroupMemberListResponse>(
    `/api/v1/vault/groups/${encodeURIComponent(groupId)}/members`,
  );
}

export async function addGroupMember(
  groupId: string,
  input: VaultGroupMemberAddInput,
): Promise<VaultGroupMemberView> {
  return apiFetch<VaultGroupMemberView>(
    `/api/v1/vault/groups/${encodeURIComponent(groupId)}/members`,
    {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function removeGroupMember(
  groupId: string,
  userId: string,
): Promise<void> {
  await apiFetch<void>(
    `/api/v1/vault/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(userId)}`,
    { method: "DELETE" },
  );
}

// ---------------------------------------------------------------------------
// Sharing (ADR-0017)

export interface VaultUserPubkeyView {
  user_id: string;
  x25519_pubkey_b64: string;
}

export interface VaultSecretWrapAddInput {
  user_id: string;
  group_id?: string | null;
  wrapped_key_b64: string;
}

export interface VaultSecretAddWrapsBody {
  wraps: VaultSecretWrapAddInput[];
}

export async function getUserPubkey(
  userId: string,
): Promise<VaultUserPubkeyView> {
  return apiFetch<VaultUserPubkeyView>(
    `/api/v1/vault/users/${encodeURIComponent(userId)}/pubkey`,
  );
}

export interface VaultUserPubkeysBulkResponse {
  data: VaultUserPubkeyView[];
}

/**
 * Batch X25519 pubkey lookup для share-with-group / rotation flows.
 *
 * Один POST вместо N sequential GET'ов; решает latency для групп >50.
 * Backend пропускает user'ов без vault setup (не error); caller сам
 * решает skip+warn.
 *
 * Order `data` соответствует `userIds` input order'у, что упрощает
 * progress indication в UI.
 */
export async function getUserPubkeysBulk(
  userIds: string[],
): Promise<VaultUserPubkeysBulkResponse> {
  return apiFetch<VaultUserPubkeysBulkResponse>(
    "/api/v1/vault/users/pubkeys",
    {
      method: "POST",
      body: JSON.stringify({ user_ids: userIds }),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function addSecretWraps(
  secretId: string,
  body: VaultSecretAddWrapsBody,
): Promise<void> {
  await apiFetch<void>(
    `/api/v1/vault/secrets/${encodeURIComponent(secretId)}/wraps`,
    {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
    },
  );
}

export async function removeSecretWrap(
  secretId: string,
  userId: string,
): Promise<void> {
  await apiFetch<void>(
    `/api/v1/vault/secrets/${encodeURIComponent(secretId)}/wraps/${encodeURIComponent(userId)}`,
    { method: "DELETE" },
  );
}

/**
 * ADR-0017 §E — list current recipients (owner-only). Используется
 * rotation UI flow'ом чтобы знать кого re-wrap'нуть после revoke.
 * Response не содержит wrapped_key bytes (zero-knowledge property).
 */
export async function listSecretWraps(
  secretId: string,
): Promise<VaultSecretWrapListResponse> {
  return apiFetch<VaultSecretWrapListResponse>(
    `/api/v1/vault/secrets/${encodeURIComponent(secretId)}/wraps`,
  );
}

/**
 * ADR-0017 §E — atomic key rotation. Owner-only. Server атомарно
 * заменяет blob ciphertext + все wraps (DELETE all + INSERT new_wraps);
 * bump'ает payload_version. Прерывает «cached plaintext» exposure
 * у revoked recipients.
 *
 * Caller (UI) отвечает за crypto flow client-side:
 *   1. decrypt текущий blob с current secret_key (через wrapped_key_b64)
 *   2. generate новый secret_key (32 random bytes)
 *   3. re-encrypt blob с новым secret_key
 *   4. для каждого surviving recipient'а: getUserPubkey + wrapSecretKeyForGroup
 *   5. POST /rotate с {new_blob, expected_version, new_wraps[]}
 */
export async function rotateVaultSecret(
  id: string,
  input: VaultSecretRotateInput,
): Promise<VaultSecretView> {
  return apiFetch<VaultSecretView>(
    `/api/v1/vault/secrets/${encodeURIComponent(id)}/rotate`,
    {
      method: "POST",
      body: JSON.stringify(input),
      headers: { "Content-Type": "application/json" },
    },
  );
}

// ---------------------------------------------------------------------------
// TOTP 2FA (ADR-0016 Slice 4)

export interface VaultTotpSetupInput {
  /** TOTP secret (RFC 6238 base32) → AES-GCM encrypted под vaultKey → base64. */
  totp_secret_encrypted_b64: string;
}

export async function setupTotp(input: VaultTotpSetupInput): Promise<VaultMeView> {
  return apiFetch<VaultMeView>("/api/v1/vault/totp/setup", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export async function disableTotp(): Promise<void> {
  await apiFetch<void>("/api/v1/vault/totp", { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// FIDO2 / WebAuthn (ADR-0022 A)

/**
 * PublicKeyCredentialCreationOptions / RequestOptions — backend сериализует
 * via py_webauthn's `options_to_json` (base64url-encoded buffers). Client
 * декодирует → ArrayBuffer перед передачей в navigator.credentials.
 *
 * Browser-returned attestation/assertion responses закодированы базой
 * `JSON.stringify`-friendly shape (base64url для bytes) и шлются на backend
 * как-есть; py_webauthn принимает dict напрямую.
 */
export interface FIDO2OptionsResponse {
  options: Record<string, unknown>;
}

export interface FIDO2RegisterCompleteInput {
  credential: Record<string, unknown>;
  nickname?: string | null;
}

export interface FIDO2AssertCompleteInput {
  credential: Record<string, unknown>;
}

export interface FIDO2CredentialView {
  id: string;
  nickname: string | null;
  created_at: string;
  last_used_at: string | null;
  transports: string[];
}

export interface FIDO2CredentialListResponse {
  data: FIDO2CredentialView[];
}

export async function fido2RegisterBegin(
  userDisplayName?: string,
): Promise<FIDO2OptionsResponse> {
  return apiFetch<FIDO2OptionsResponse>("/api/v1/vault/fido2/register-begin", {
    method: "POST",
    body: JSON.stringify({ user_display_name: userDisplayName ?? null }),
    headers: { "Content-Type": "application/json" },
  });
}

export async function fido2RegisterComplete(
  input: FIDO2RegisterCompleteInput,
): Promise<FIDO2CredentialView> {
  return apiFetch<FIDO2CredentialView>("/api/v1/vault/fido2/register-complete", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export async function fido2AssertBegin(): Promise<FIDO2OptionsResponse> {
  return apiFetch<FIDO2OptionsResponse>("/api/v1/vault/fido2/assert-begin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
}

export async function fido2AssertComplete(
  input: FIDO2AssertCompleteInput,
): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/api/v1/vault/fido2/assert-complete", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export async function listFido2Credentials(): Promise<FIDO2CredentialListResponse> {
  return apiFetch<FIDO2CredentialListResponse>("/api/v1/vault/fido2/credentials");
}

export async function deleteFido2Credential(credentialId: string): Promise<void> {
  await apiFetch<void>(
    `/api/v1/vault/fido2/credentials/${encodeURIComponent(credentialId)}`,
    { method: "DELETE" },
  );
}

// ---------------------------------------------------------------------------
// Emergency access — escrow ceremony (ADR-0021 A)

export interface VaultSetupEscrowInput {
  escrow_wrap_b64: string;
}

export interface VaultSetupEscrowResponse {
  has_escrow: boolean;
}

export async function setupEscrow(
  input: VaultSetupEscrowInput,
): Promise<VaultSetupEscrowResponse> {
  return apiFetch<VaultSetupEscrowResponse>("/api/v1/vault/setup-escrow", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}

export type EmergencyReasonCategory =
  | "incident"
  | "legal_order"
  | "employee_departure"
  | "forensic_audit"
  | "password_lost";

export interface VaultEmergencyUnlockInput {
  target_user_id: string;
  reason_category: EmergencyReasonCategory;
  reason_text: string;
}

export interface VaultEmergencyPayload {
  escrow_wrap_b64: string;
  encrypted_x25519_privkey_b64: string;
  x25519_pubkey_b64: string;
  argon_salt_b64: string;
}

export interface VaultEmergencyUnlockResponse {
  unlock_log_id: string;
  security_incident_id: string;
  rkn_notify_required: boolean;
  severity: string;
  created_at: string;
  vault: VaultEmergencyPayload;
}

export async function emergencyUnlock(
  input: VaultEmergencyUnlockInput,
): Promise<VaultEmergencyUnlockResponse> {
  return apiFetch<VaultEmergencyUnlockResponse>("/api/v1/admin/vault/emergency-unlock", {
    method: "POST",
    body: JSON.stringify(input),
    headers: { "Content-Type": "application/json" },
  });
}
