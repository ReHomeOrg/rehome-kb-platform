/**
 * Crypto-module tests (ADR-0016 §«Crypto API contract»).
 *
 * Подход: round-trip integration tests + property checks. Argon2id с
 * полными параметрами (64 MiB / 3 iter) — медленный, выполняется один
 * раз для `deriveKeys` test'а; остальные тесты используют уже derived
 * vaultKey либо ad-hoc keys.
 *
 * KAT vector тесты (RFC 9106 Argon2id / RFC 7748 X25519) не дублируем
 * на наших wrapper'ах — это упражнение для upstream библиотек.
 */

import { describe, expect, it } from "vitest";

import {
  decryptBlob,
  deriveKeys,
  encryptBlob,
  fromBase64,
  generateSalt,
  generateSecretKey,
  generateX25519Keypair,
  randomBytes,
  toBase64,
  unwrapSecretKeyForGroup,
  unwrapSecretKeyForUser,
  unwrapX25519Privkey,
  wrapSecretKeyForGroup,
  wrapSecretKeyForUser,
  wrapX25519Privkey,
} from "./crypto";

describe("encoding helpers", () => {
  it("base64 round-trip", () => {
    const original = new Uint8Array([0, 1, 2, 250, 255]);
    expect(fromBase64(toBase64(original))).toEqual(original);
  });

  it("randomBytes returns requested length and not-all-zero", () => {
    const a = randomBytes(32);
    expect(a.length).toBe(32);
    expect(a.some((b) => b !== 0)).toBe(true);
  });

  it("generateSalt produces 16 bytes", () => {
    expect(generateSalt().length).toBe(16);
  });

  it("randomBytes(N) produces different output на consecutive calls", () => {
    const a = randomBytes(32);
    const b = randomBytes(32);
    expect(a).not.toEqual(b);
  });
});

// deriveKeys тяжёлый (~500ms за счёт Argon2id 64 MiB / 3 iter).
// Один тест, проверяет invariants одновременно.
describe("deriveKeys (Argon2id + HKDF)", () => {
  it(
    "same password+salt → identical authHash; different salt → different authHash",
    async () => {
      const password = "MasterPassword123!";
      const salt = generateSalt();
      const keys1 = await deriveKeys(password, salt);
      const keys2 = await deriveKeys(password, salt);
      expect(toBase64(keys1.authHash)).toBe(toBase64(keys2.authHash));
      expect(keys1.authHash.length).toBe(32);
      // vaultKey non-extractable.
      expect(keys1.vaultKey.extractable).toBe(false);

      const salt2 = generateSalt();
      const keys3 = await deriveKeys(password, salt2);
      expect(toBase64(keys3.authHash)).not.toBe(toBase64(keys1.authHash));
    },
    20000,
  );

  it("rejects empty password", async () => {
    await expect(deriveKeys("", generateSalt())).rejects.toThrow(
      /password must not be empty/,
    );
  });

  it("rejects salt of wrong length", async () => {
    await expect(deriveKeys("x", new Uint8Array(8))).rejects.toThrow(
      /salt must be 16 bytes/,
    );
  });
});

describe("AES-GCM encryptBlob / decryptBlob", () => {
  it("round-trip preserves UTF-8 plaintext", async () => {
    const key = await generateSecretKey();
    const plaintext = "пароль 123 — секрет 🔑";
    const blob = await encryptBlob(key, plaintext);
    // Blob = iv(12) || ct + tag. Min length: 12 + 16 (tag) = 28 для пустого
    // plaintext; здесь больше.
    expect(blob.length).toBeGreaterThanOrEqual(12 + 16);
    const decoded = await decryptBlob(key, blob);
    expect(decoded).toBe(plaintext);
  });

  it("decrypt fails on tampered ciphertext", async () => {
    const key = await generateSecretKey();
    const blob = await encryptBlob(key, "secret");
    blob[blob.length - 1] ^= 0xff; // flip last byte of tag
    await expect(decryptBlob(key, blob)).rejects.toBeTruthy();
  });

  it("decrypt fails on too-short blob", async () => {
    const key = await generateSecretKey();
    await expect(decryptBlob(key, new Uint8Array(5))).rejects.toThrow(
      /too short/,
    );
  });

  it("decrypt fails with wrong key", async () => {
    const key1 = await generateSecretKey();
    const key2 = await generateSecretKey();
    const blob = await encryptBlob(key1, "secret");
    await expect(decryptBlob(key2, blob)).rejects.toBeTruthy();
  });
});

describe("wrapSecretKeyForUser / unwrapSecretKeyForUser", () => {
  // Используем уже-derived vaultKey ради скорости; повторно не дёргаем
  // Argon2id.
  async function makeFakeVaultKey(): Promise<CryptoKey> {
    return crypto.subtle.generateKey(
      { name: "AES-GCM", length: 256 },
      false,
      ["wrapKey", "unwrapKey", "encrypt", "decrypt"],
    );
  }

  it("round-trip: wrap secretKey under vaultKey, unwrap, decrypt blob", async () => {
    const vaultKey = await makeFakeVaultKey();
    const secretKey = await generateSecretKey();
    const blob = await encryptBlob(secretKey, "my password");
    const wrapped = await wrapSecretKeyForUser(vaultKey, secretKey);
    const recovered = await unwrapSecretKeyForUser(vaultKey, wrapped);
    expect(await decryptBlob(recovered, blob)).toBe("my password");
  });

  it("unwrap fails with wrong vaultKey", async () => {
    const v1 = await makeFakeVaultKey();
    const v2 = await makeFakeVaultKey();
    const sk = await generateSecretKey();
    const wrapped = await wrapSecretKeyForUser(v1, sk);
    await expect(unwrapSecretKeyForUser(v2, wrapped)).rejects.toBeTruthy();
  });
});

describe("X25519 keypair + group sealed-box", () => {
  it("generateX25519Keypair produces 32-byte pubkey + privkey", () => {
    const kp = generateX25519Keypair();
    expect(kp.pubkey.length).toBe(32);
    expect(kp.privkey.length).toBe(32);
  });

  it("wrapSecretKeyForGroup / unwrapSecretKeyForGroup round-trip", async () => {
    const kp = generateX25519Keypair();
    const secretKey = await generateSecretKey();
    const blob = await encryptBlob(secretKey, "shared password");
    const wrapped = await wrapSecretKeyForGroup(kp.pubkey, secretKey);
    expect(wrapped.length).toBeGreaterThanOrEqual(32 + 12 + 16);
    const recovered = await unwrapSecretKeyForGroup(kp.privkey, wrapped);
    expect(await decryptBlob(recovered, blob)).toBe("shared password");
  });

  it("unwrap (group) fails with wrong privkey", async () => {
    const kp1 = generateX25519Keypair();
    const kp2 = generateX25519Keypair();
    const sk = await generateSecretKey();
    const wrapped = await wrapSecretKeyForGroup(kp1.pubkey, sk);
    // Either unwrapKey fails (AEAD tag mismatch) либо decryptBlob fails
    // — оба acceptable.
    await expect(
      unwrapSecretKeyForGroup(kp2.privkey, wrapped),
    ).rejects.toBeTruthy();
  });

  it("rejects wrong pubkey length", async () => {
    const sk = await generateSecretKey();
    await expect(
      wrapSecretKeyForGroup(new Uint8Array(16), sk),
    ).rejects.toThrow(/32 bytes/);
  });
});

describe("X25519 privkey wrap/unwrap (storage)", () => {
  async function makeFakeVaultKey(): Promise<CryptoKey> {
    return crypto.subtle.generateKey(
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt", "decrypt"],
    );
  }

  it("round-trip preserves 32-byte privkey", async () => {
    const vaultKey = await makeFakeVaultKey();
    const kp = generateX25519Keypair();
    const wrapped = await wrapX25519Privkey(vaultKey, kp.privkey);
    const recovered = await unwrapX25519Privkey(vaultKey, wrapped);
    expect(recovered).toEqual(kp.privkey);
  });

  it("rejects wrong privkey length", async () => {
    const vaultKey = await makeFakeVaultKey();
    await expect(
      wrapX25519Privkey(vaultKey, new Uint8Array(16)),
    ).rejects.toThrow(/32 bytes/);
  });
});
