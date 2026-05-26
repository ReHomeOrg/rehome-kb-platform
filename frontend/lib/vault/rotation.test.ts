/**
 * E2E rotation crypto round-trip (ADR-0017 §E true revoke).
 *
 * Закрывает coverage gap из Reviewer pass 2026-05-27: backend unit
 * tests + frontend component tests существовали, но НИ ОДИН не делал
 * полный round-trip:
 *   create (encrypt) → share → rotate → unlock with survivor key → decrypt.
 *
 * Именно такой тест поймал бы title-bug из PR #337 (title не
 * re-encrypted после rotation → undecryptable forever).
 *
 * Тест использует РЕАЛЬНЫЕ WebCrypto + @noble/curves primitives —
 * имитирует точно ту же последовательность что выполняет
 * `RecipientsPanel.onRevoke` + backend `rotate_secret_atomic`.
 */

import { describe, expect, it } from "vitest";

import {
  decryptBlob,
  encryptBlob,
  generateSecretKey,
  generateX25519Keypair,
  unwrapSecretKeyForGroup,
  unwrapSecretKeyForUser,
  wrapSecretKeyForGroup,
  wrapSecretKeyForUser,
} from "./crypto";

/** Test helper: AES-GCM key с wrapKey/unwrapKey usages (simulates vaultKey). */
async function makeVaultKey(): Promise<CryptoKey> {
  return crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    false,
    ["wrapKey", "unwrapKey"],
  );
}

describe("Vault rotation crypto round-trip (ADR-0017 §E)", () => {
  it("create → share → rotate (revoke user-B) → survivor C still decrypts title + blob", async () => {
    // ---- Setup phase ----
    // Owner setup: vault key + X25519 keypair (для self-receive sharing).
    const ownerVaultKey = await makeVaultKey();
    const ownerKeypair = generateX25519Keypair();

    // User-B (will be revoked) and User-C (will survive): X25519 keypairs.
    const userBKeypair = generateX25519Keypair();
    const userCKeypair = generateX25519Keypair();

    // ---- Phase 1: Create secret with initial encryption ----
    const originalTitle = "My API token (do not lose!)";
    const originalPayload = JSON.stringify({
      service: "api.example.com",
      token: "ghp_secret_token_42",
      created: "2026-05-27",
    });

    const secretKeyV1 = await generateSecretKey();
    const titleCtV1 = await encryptBlob(secretKeyV1, originalTitle);
    const blobCtV1 = await encryptBlob(secretKeyV1, originalPayload);

    // Self-wrap для owner'а (через vault key).
    const ownerWrapV1 = await wrapSecretKeyForUser(ownerVaultKey, secretKeyV1);

    // ---- Phase 2: Share с B и C (X25519 sealed-box) ----
    const userBWrapV1 = await wrapSecretKeyForGroup(
      userBKeypair.pubkey,
      secretKeyV1,
    );
    const userCWrapV1 = await wrapSecretKeyForGroup(
      userCKeypair.pubkey,
      secretKeyV1,
    );

    // Sanity check: User-B и User-C могут decrypt v1 title + blob.
    {
      const bSecretKey = await unwrapSecretKeyForGroup(
        userBKeypair.privkey,
        userBWrapV1,
      );
      expect(await decryptBlob(bSecretKey, titleCtV1)).toBe(originalTitle);
      expect(await decryptBlob(bSecretKey, blobCtV1)).toBe(originalPayload);

      const cSecretKey = await unwrapSecretKeyForGroup(
        userCKeypair.privkey,
        userCWrapV1,
      );
      expect(await decryptBlob(cSecretKey, titleCtV1)).toBe(originalTitle);
      expect(await decryptBlob(cSecretKey, blobCtV1)).toBe(originalPayload);
    }

    // ---- Phase 3: ROTATION — revoke User-B ----
    // Owner decrypts current state (имитирует state, который RecipientsPanel
    // получает из parent's secret-detail.tsx).
    const ownerSecretKeyV1 = await unwrapSecretKeyForUser(
      ownerVaultKey,
      ownerWrapV1,
    );
    const decryptedTitle = await decryptBlob(ownerSecretKeyV1, titleCtV1);
    const decryptedPayload = await decryptBlob(ownerSecretKeyV1, blobCtV1);
    expect(decryptedTitle).toBe(originalTitle);
    expect(decryptedPayload).toBe(originalPayload);

    // Owner generates NEW secret_key, re-encrypts BOTH title and blob.
    // (Тот самый шаг, который PR #337 пропускал для title.)
    const secretKeyV2 = await generateSecretKey();
    const titleCtV2 = await encryptBlob(secretKeyV2, decryptedTitle);
    const blobCtV2 = await encryptBlob(secretKeyV2, decryptedPayload);

    // Wrap новый secret_key для survivors: owner (self-wrap) + User-C.
    // User-B НЕ включается — он revoked.
    const ownerWrapV2 = await wrapSecretKeyForUser(ownerVaultKey, secretKeyV2);
    const userCWrapV2 = await wrapSecretKeyForGroup(
      userCKeypair.pubkey,
      secretKeyV2,
    );

    // ---- Phase 4: Verification — survivors decrypt new ciphertexts ----
    // Owner decrypts с новым wrap'ом → новый secret_key → title + blob OK.
    {
      const ownerKeyV2 = await unwrapSecretKeyForUser(
        ownerVaultKey,
        ownerWrapV2,
      );
      expect(await decryptBlob(ownerKeyV2, titleCtV2)).toBe(originalTitle);
      expect(await decryptBlob(ownerKeyV2, blobCtV2)).toBe(originalPayload);
    }

    // User-C decrypts с новым wrap'ом → новый secret_key → title + blob OK.
    {
      const cKeyV2 = await unwrapSecretKeyForGroup(
        userCKeypair.privkey,
        userCWrapV2,
      );
      expect(await decryptBlob(cKeyV2, titleCtV2)).toBe(originalTitle);
      expect(await decryptBlob(cKeyV2, blobCtV2)).toBe(originalPayload);
    }

    // ---- Phase 5: SECURITY ASSERT — User-B can no longer decrypt v2 ----
    // User-B всё ещё имеет his old wrap (userBWrapV1) от secretKeyV1. Но
    // server-side старый wrap уже DELETE'нут (atomic rotation). Cache'ит
    // он его браузером — это эквивалент.
    const bOldSecretKey = await unwrapSecretKeyForGroup(
      userBKeypair.privkey,
      userBWrapV1,
    );

    // User-B всё ещё может decrypt v1 (что у него уже cached в RAM).
    expect(await decryptBlob(bOldSecretKey, titleCtV1)).toBe(originalTitle);
    expect(await decryptBlob(bOldSecretKey, blobCtV1)).toBe(originalPayload);

    // НО: User-B не может decrypt v2 (новые ciphertext'ы) — старый key
    // не подходит. AES-GCM tag mismatch → exception.
    await expect(decryptBlob(bOldSecretKey, titleCtV2)).rejects.toThrow();
    await expect(decryptBlob(bOldSecretKey, blobCtV2)).rejects.toThrow();
  });

  it("REGRESSION (PR #337 bug): title без re-encrypt становится undecryptable", async () => {
    // Этот тест документирует bug который был в PR #337: rotate'или blob,
    // но title оставался encrypted под старым secret_key. После rotation
    // никто (включая owner'а) не мог decrypt title — старый key уже не
    // unwrap'ится никем, новый key для title не подходит.

    const ownerVaultKey = await makeVaultKey();
    const originalTitle = "Will become unrecoverable";
    const originalPayload = "payload";

    // V1.
    const secretKeyV1 = await generateSecretKey();
    const titleCtV1 = await encryptBlob(secretKeyV1, originalTitle);
    // const blobCtV1 = await encryptBlob(secretKeyV1, originalPayload); // unused — мы не storим v1 blob

    // V2 — re-encrypt ТОЛЬКО blob (имитируем bug PR #337).
    const secretKeyV2 = await generateSecretKey();
    // const titleCtV2 = titleCtV1;  // BUG: title НЕ re-encrypted
    const blobCtV2 = await encryptBlob(secretKeyV2, originalPayload);
    const ownerWrapV2 = await wrapSecretKeyForUser(ownerVaultKey, secretKeyV2);

    // Owner получает wrap v2 → unwrap → secretKeyV2. Пытается decrypt
    // оба ciphertext'а с secretKeyV2.
    const ownerKeyV2 = await unwrapSecretKeyForUser(ownerVaultKey, ownerWrapV2);

    // Blob OK (re-encrypted с V2).
    expect(await decryptBlob(ownerKeyV2, blobCtV2)).toBe(originalPayload);

    // Title FAIL — V1 ciphertext под V2 key не decrypts.
    await expect(decryptBlob(ownerKeyV2, titleCtV1)).rejects.toThrow();

    // Это и есть data corruption из PR #337. Backend сегодня re-encrypts
    // title в rotate_secret_atomic step 5 (см. repository.py).
  });
});
