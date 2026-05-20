/**
 * kb-vault client-side crypto primitives (ADR-0011 + ADR-0016).
 *
 * Zero-knowledge: ничего из этого модуля не отправляется на сервер
 * кроме `authHash`, `argonSalt` (на setup), `wrapped_*` blobs, и
 * encrypted ciphertexts. `vaultKey` живёт ТОЛЬКО на клиенте, в памяти,
 * non-extractable (см. session.ts).
 *
 * Параметры из ADR-0011 §«Crypto specification»:
 * - Argon2id: 64 MiB / 3 iter / parallelism 4 / 32-byte output / 16-byte salt.
 * - HKDF-SHA256: splits master_key → vaultKey + authHash через info tags.
 * - AES-256-GCM: 12-byte IV, blob format = `iv || ciphertext || tag`.
 * - X25519 (Curve25519) sealed_box-style для group wrapping.
 *
 * Все функции async (WebCrypto + WASM требуют). Throw on invalid input
 * (вместо silent return) — caller catches и показывает user-friendly error.
 */

import { x25519 } from "@noble/curves/ed25519.js";
import { argon2id } from "hash-wasm";

// Tier-1 invariants (ADR-0011).
const ARGON2_MEMORY_KIB = 64 * 1024; // 64 MiB
const ARGON2_ITERATIONS = 3;
const ARGON2_PARALLELISM = 4;
const ARGON2_OUTPUT_BYTES = 32;
const ARGON2_SALT_BYTES = 16;

const AES_KEY_BITS = 256;
const AES_IV_BYTES = 12;

const HKDF_INFO_VAULT = "vault-encrypt";
const HKDF_INFO_AUTH = "vault-auth";

// ---------------------------------------------------------------------------
// CSPRNG / encoding helpers

export function randomBytes(length: number): Uint8Array {
  const buf = new Uint8Array(length);
  crypto.getRandomValues(buf);
  return buf;
}

export function generateSalt(): Uint8Array {
  return randomBytes(ARGON2_SALT_BYTES);
}

export function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]!);
  }
  return btoa(binary);
}

/**
 * Cast Uint8Array → BufferSource accepted WebCrypto API.
 *
 * TS 5.7 ужесточил типизацию: `Uint8Array<ArrayBufferLike>` (default
 * literal) ≠ `Uint8Array<ArrayBuffer>` (требуется BufferSource). Cast
 * safe — runtime ArrayBuffer всегда (SharedArrayBuffer не используем).
 */
function bs(bytes: Uint8Array): BufferSource {
  return bytes as unknown as BufferSource;
}

export function fromBase64(b64: string): Uint8Array {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    out[i] = binary.charCodeAt(i);
  }
  return out;
}

function utf8(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

function fromUtf8(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes);
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Key derivation

export interface DerivedKeys {
  /** Non-extractable AES-GCM key для wrapping. Не покидает Browser context. */
  vaultKey: CryptoKey;
  /** Отправляется на сервер для auth check. 32 байта. */
  authHash: Uint8Array;
}

/**
 * Argon2id(password, salt) → master_key → HKDF split → (vaultKey, authHash).
 *
 * `vaultKey` import'ится с `extractable=false`: ни один JS код не может
 * через `crypto.subtle.exportKey` достать raw bytes (defense-in-depth от
 * XSS dump'ов; не bulletproof — память всё равно read'абельна через
 * other side-channels, но raises the bar).
 *
 * `authHash` — экспортируемый Uint8Array, т.к. по definition уходит
 * на сервер (POST /vault/setup + /vault/unlock).
 */
export async function deriveKeys(
  password: string,
  salt: Uint8Array,
): Promise<DerivedKeys> {
  if (salt.length !== ARGON2_SALT_BYTES) {
    throw new Error(
      `salt must be ${ARGON2_SALT_BYTES} bytes, got ${salt.length}`,
    );
  }
  if (password.length === 0) {
    throw new Error("password must not be empty");
  }

  const masterKeyBytes = await argon2id({
    password,
    salt,
    iterations: ARGON2_ITERATIONS,
    memorySize: ARGON2_MEMORY_KIB,
    parallelism: ARGON2_PARALLELISM,
    hashLength: ARGON2_OUTPUT_BYTES,
    outputType: "binary",
  });

  // Import master_key как HKDF source, derive twice with different info tags.
  const hkdfKey = await crypto.subtle.importKey(
    "raw",
    bs(masterKeyBytes),
    "HKDF",
    false,
    ["deriveBits"],
  );
  const vaultBits = await crypto.subtle.deriveBits(
    {
      name: "HKDF",
      hash: "SHA-256",
      salt: bs(new Uint8Array(0)),
      info: bs(utf8(HKDF_INFO_VAULT)),
    },
    hkdfKey,
    AES_KEY_BITS,
  );
  const authBits = await crypto.subtle.deriveBits(
    {
      name: "HKDF",
      hash: "SHA-256",
      salt: bs(new Uint8Array(0)),
      info: bs(utf8(HKDF_INFO_AUTH)),
    },
    hkdfKey,
    256,
  );

  const vaultKey = await crypto.subtle.importKey(
    "raw",
    vaultBits,
    { name: "AES-GCM", length: AES_KEY_BITS },
    /* extractable */ false,
    ["wrapKey", "unwrapKey", "encrypt", "decrypt"],
  );

  return {
    vaultKey,
    authHash: new Uint8Array(authBits),
  };
}

// ---------------------------------------------------------------------------
// Per-secret crypto: AES-256-GCM with random 12-byte IV

/**
 * Generate fresh AES-256-GCM key (extractable=true т.к. эта ключ
 * нужно wrap'ить master vaultKey'ом перед отправкой на сервер).
 *
 * NB: extractable=true критично: иначе wrapSecretKey не сможет получить
 * raw bytes ключа для шифрования. Trade-off: per-secret key короткоживущая
 * в памяти, только в момент create/decrypt.
 */
export async function generateSecretKey(): Promise<CryptoKey> {
  return crypto.subtle.generateKey(
    { name: "AES-GCM", length: AES_KEY_BITS },
    /* extractable */ true,
    ["encrypt", "decrypt"],
  );
}

/**
 * Re-derive raw KEK bytes from password — ceremony-only path для
 * emergency access setup (ADR-0021 A).
 *
 * Standard `deriveKeys` returns non-extractable CryptoKey (ADR-0016 §D).
 * Escrow ceremony needs raw KEK bytes to wrap under escrow_key. Caller
 * MUST zero the returned array immediately after use (`array.fill(0)`).
 *
 * Same Argon2id + HKDF params как `deriveKeys` — must produce identical
 * KEK bytes для consistency с unlock flow.
 */
export async function deriveExtractableKek(
  password: string,
  argonSalt: Uint8Array,
): Promise<Uint8Array> {
  const masterKey = await argon2id({
    password,
    salt: argonSalt,
    parallelism: ARGON2_PARALLELISM,
    iterations: ARGON2_ITERATIONS,
    memorySize: ARGON2_MEMORY_KIB,
    hashLength: ARGON2_OUTPUT_BYTES,
    outputType: "binary",
  });

  const hkdfKey = await crypto.subtle.importKey(
    "raw",
    bs(masterKey),
    { name: "HKDF" },
    /* extractable */ false,
    ["deriveBits"],
  );
  const vaultBits = await crypto.subtle.deriveBits(
    {
      name: "HKDF",
      hash: "SHA-256",
      salt: bs(new Uint8Array(0)),
      info: bs(utf8(HKDF_INFO_VAULT)),
    },
    hkdfKey,
    256,
  );
  return new Uint8Array(vaultBits);
}

/** Encrypt plaintext (string) → `iv || ciphertext || tag` byte array. */
export async function encryptBlob(
  secretKey: CryptoKey,
  plaintext: string,
): Promise<Uint8Array> {
  const iv = randomBytes(AES_IV_BYTES);
  const cipherBuf = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: bs(iv) },
    secretKey,
    bs(utf8(plaintext)),
  );
  return concat(iv, new Uint8Array(cipherBuf));
}

/** Decrypt `iv || ciphertext || tag` → plaintext string. Throws on tamper. */
export async function decryptBlob(
  secretKey: CryptoKey,
  blob: Uint8Array,
): Promise<string> {
  if (blob.length < AES_IV_BYTES + 16) {
    throw new Error("blob too short (must be iv + ciphertext + 16-byte tag)");
  }
  const iv = blob.slice(0, AES_IV_BYTES);
  const ct = blob.slice(AES_IV_BYTES);
  const plainBuf = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: bs(iv) },
    secretKey,
    bs(ct),
  );
  return fromUtf8(new Uint8Array(plainBuf));
}

// ---------------------------------------------------------------------------
// Wrapping: per-secret key under master vaultKey (personal access)

/** Wrap raw secret key bytes под vaultKey (AES-GCM). Output: `iv || ciphertext`. */
export async function wrapSecretKeyForUser(
  vaultKey: CryptoKey,
  secretKey: CryptoKey,
): Promise<Uint8Array> {
  const iv = randomBytes(AES_IV_BYTES);
  // wrapKey expects either format='raw' or format='jwk'. AES-GCM
  // exportable секрет key → raw 32 bytes.
  const wrapped = await crypto.subtle.wrapKey(
    "raw",
    secretKey,
    vaultKey,
    { name: "AES-GCM", iv: bs(iv) },
  );
  return concat(iv, new Uint8Array(wrapped));
}

/** Unwrap (vaultKey, blob) → CryptoKey. */
export async function unwrapSecretKeyForUser(
  vaultKey: CryptoKey,
  wrapped: Uint8Array,
): Promise<CryptoKey> {
  if (wrapped.length < AES_IV_BYTES + 16) {
    throw new Error("wrapped key too short");
  }
  const iv = wrapped.slice(0, AES_IV_BYTES);
  const ct = wrapped.slice(AES_IV_BYTES);
  return crypto.subtle.unwrapKey(
    "raw",
    bs(ct),
    vaultKey,
    { name: "AES-GCM", iv: bs(iv) },
    { name: "AES-GCM", length: AES_KEY_BITS },
    /* extractable */ true,
    ["encrypt", "decrypt"],
  );
}

// ---------------------------------------------------------------------------
// X25519 keypair + group wrapping (sealed_box pattern)
//
// Sealed box: ephemeral_keypair → ECDH с recipient pubkey → AES-GCM с
// derived key. Recipient знает свой privkey, ephemeral_pubkey передаётся
// в blob. Перфектная forward secrecy не требуется (recipient privkey
// statтиc), но конструкция совпадает с libsodium sealed_box для будущей
// CLI-совместимости.

export interface X25519Keypair {
  pubkey: Uint8Array; // 32 bytes
  privkey: Uint8Array; // 32 bytes
}

export function generateX25519Keypair(): X25519Keypair {
  const privkey = x25519.utils.randomSecretKey();
  const pubkey = x25519.getPublicKey(privkey);
  return { pubkey, privkey };
}

async function deriveAesFromSharedSecret(
  shared: Uint8Array,
): Promise<CryptoKey> {
  // HKDF-SHA256 of shared secret → AES-GCM 256 key (non-extractable).
  const hkdfKey = await crypto.subtle.importKey(
    "raw",
    bs(shared),
    "HKDF",
    false,
    ["deriveBits"],
  );
  const keyBits = await crypto.subtle.deriveBits(
    {
      name: "HKDF",
      hash: "SHA-256",
      salt: bs(new Uint8Array(0)),
      info: bs(utf8("vault-x25519-sealed")),
    },
    hkdfKey,
    AES_KEY_BITS,
  );
  return crypto.subtle.importKey(
    "raw",
    keyBits,
    { name: "AES-GCM", length: AES_KEY_BITS },
    false,
    ["encrypt", "decrypt"],
  );
}

/**
 * Wrap secret key для recipient X25519 pubkey.
 * Output format: `ephemeral_pubkey(32) || iv(12) || ciphertext`.
 */
export async function wrapSecretKeyForGroup(
  groupPubkey: Uint8Array,
  secretKey: CryptoKey,
): Promise<Uint8Array> {
  if (groupPubkey.length !== 32) {
    throw new Error(`groupPubkey must be 32 bytes, got ${groupPubkey.length}`);
  }
  const ephemeralPriv = x25519.utils.randomSecretKey();
  const ephemeralPub = x25519.getPublicKey(ephemeralPriv);
  const shared = x25519.getSharedSecret(ephemeralPriv, groupPubkey);
  const aesKey = await deriveAesFromSharedSecret(shared);

  // Export secret key raw для wrap'а через AES-GCM encrypt.
  const secretRaw = await crypto.subtle.exportKey("raw", secretKey);
  const iv = randomBytes(AES_IV_BYTES);
  const ctBuf = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: bs(iv) },
    aesKey,
    secretRaw,
  );
  return concat(ephemeralPub, iv, new Uint8Array(ctBuf));
}

export async function unwrapSecretKeyForGroup(
  groupPrivkey: Uint8Array,
  wrapped: Uint8Array,
): Promise<CryptoKey> {
  if (groupPrivkey.length !== 32) {
    throw new Error(`groupPrivkey must be 32 bytes`);
  }
  if (wrapped.length < 32 + AES_IV_BYTES + 16) {
    throw new Error("wrapped (group) too short");
  }
  const ephemeralPub = wrapped.slice(0, 32);
  const iv = wrapped.slice(32, 32 + AES_IV_BYTES);
  const ct = wrapped.slice(32 + AES_IV_BYTES);
  const shared = x25519.getSharedSecret(groupPrivkey, ephemeralPub);
  const aesKey = await deriveAesFromSharedSecret(shared);
  const rawBuf = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: bs(iv) },
    aesKey,
    bs(ct),
  );
  return crypto.subtle.importKey(
    "raw",
    rawBuf,
    { name: "AES-GCM", length: AES_KEY_BITS },
    /* extractable */ true,
    ["encrypt", "decrypt"],
  );
}

// ---------------------------------------------------------------------------
// X25519 privkey at-rest: wrap под vaultKey (для server storage)

export async function wrapX25519Privkey(
  vaultKey: CryptoKey,
  privkey: Uint8Array,
): Promise<Uint8Array> {
  if (privkey.length !== 32) {
    throw new Error("privkey must be 32 bytes");
  }
  const iv = randomBytes(AES_IV_BYTES);
  const ctBuf = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: bs(iv) },
    vaultKey,
    bs(privkey),
  );
  return concat(iv, new Uint8Array(ctBuf));
}

export async function unwrapX25519Privkey(
  vaultKey: CryptoKey,
  wrapped: Uint8Array,
): Promise<Uint8Array> {
  if (wrapped.length < AES_IV_BYTES + 16) {
    throw new Error("wrapped privkey too short");
  }
  const iv = wrapped.slice(0, AES_IV_BYTES);
  const ct = wrapped.slice(AES_IV_BYTES);
  const buf = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: bs(iv) },
    vaultKey,
    bs(ct),
  );
  return new Uint8Array(buf);
}
