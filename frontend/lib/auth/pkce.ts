/**
 * PKCE (Proof Key for Code Exchange) — RFC 7636.
 *
 * Используется браузерным клиентом для защиты Authorization Code Grant от
 * code injection / interception атак.
 */

const VERIFIER_BYTES = 32;

/**
 * Generate a cryptographically random code_verifier.
 *
 * Возвращает base64url-без-padding строку (43-128 символов из набора
 * `[A-Z a-z 0-9 - _]`), как требует RFC 7636 §4.1.
 */
export function generateCodeVerifier(): string {
  const buf = new Uint8Array(VERIFIER_BYTES);
  crypto.getRandomValues(buf);
  return base64UrlEncode(buf);
}

/**
 * Compute the code_challenge from a code_verifier using S256 method.
 *
 * `code_challenge = base64url(sha256(code_verifier))`.
 * См. RFC 7636 §4.2.
 */
export async function computeCodeChallengeS256(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return base64UrlEncode(new Uint8Array(hash));
}

/**
 * RFC 4648 §5 base64url encoding without padding.
 *
 * Стандартный base64 → замена `+`→`-`, `/`→`_`, удаление `=`.
 */
export function base64UrlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
