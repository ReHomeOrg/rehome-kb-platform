/**
 * WebAuthn ceremony helpers (ADR-0022 A).
 *
 * Browser-side adapters для py_webauthn-сериализованных options + ответов
 * authenticator'а. Backend шлёт options как JSON с base64url-encoded
 * bytes (`challenge`, `user.id`, `excludeCredentials[].id`, etc.);
 * `navigator.credentials.create/get` ожидает `ArrayBuffer`. Browser
 * возвращает `PublicKeyCredential` с `ArrayBuffer` полями; backend
 * принимает dict с base64url strings.
 *
 * Это два mirror'а одного формата — кодирование/декодирование per поле,
 * никакой crypto-обработки на клиенте (ceremony delegated authenticator).
 */

/** Encode ArrayBuffer or Uint8Array → base64url string без padding. */
export function arrayBufferToBase64url(buffer: ArrayBuffer | Uint8Array): string {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  const b64 = btoa(binary);
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Decode base64url string → ArrayBuffer. */
export function base64urlToArrayBuffer(b64url: string): ArrayBuffer {
  const padding = "=".repeat((4 - (b64url.length % 4)) % 4);
  const b64 = (b64url + padding).replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

/**
 * Transform backend-serialised CreationOptions (base64url strings) →
 * `PublicKeyCredentialCreationOptions` consumable by `navigator.credentials.create`.
 */
export function decodeCreationOptions(
  serialised: Record<string, unknown>,
): PublicKeyCredentialCreationOptions {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const o = serialised as any;
  return {
    challenge: base64urlToArrayBuffer(o.challenge),
    rp: o.rp,
    user: {
      id: base64urlToArrayBuffer(o.user.id),
      name: o.user.name,
      displayName: o.user.displayName,
    },
    pubKeyCredParams: o.pubKeyCredParams,
    timeout: o.timeout,
    attestation: o.attestation,
    authenticatorSelection: o.authenticatorSelection,
    excludeCredentials: (o.excludeCredentials ?? []).map(
      (c: { id: string; type: string; transports?: string[] }) => ({
        id: base64urlToArrayBuffer(c.id),
        type: c.type as PublicKeyCredentialType,
        transports: c.transports as AuthenticatorTransport[] | undefined,
      }),
    ),
  };
}

/**
 * Transform backend-serialised RequestOptions → `PublicKeyCredentialRequestOptions`.
 */
export function decodeRequestOptions(
  serialised: Record<string, unknown>,
): PublicKeyCredentialRequestOptions {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const o = serialised as any;
  return {
    challenge: base64urlToArrayBuffer(o.challenge),
    timeout: o.timeout,
    rpId: o.rpId,
    userVerification: o.userVerification,
    allowCredentials: (o.allowCredentials ?? []).map(
      (c: { id: string; type: string; transports?: string[] }) => ({
        id: base64urlToArrayBuffer(c.id),
        type: c.type as PublicKeyCredentialType,
        transports: c.transports as AuthenticatorTransport[] | undefined,
      }),
    ),
  };
}

/**
 * Encode browser-returned `PublicKeyCredential` (registration) → plain dict
 * с base64url strings — backend's `verify_registration_response` принимает.
 */
export function encodeRegistrationCredential(
  credential: PublicKeyCredential,
): Record<string, unknown> {
  const response = credential.response as AuthenticatorAttestationResponse;
  const transports =
    typeof response.getTransports === "function" ? response.getTransports() : [];
  return {
    id: credential.id,
    rawId: arrayBufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: arrayBufferToBase64url(response.clientDataJSON),
      attestationObject: arrayBufferToBase64url(response.attestationObject),
      transports,
    },
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}

/**
 * Encode browser-returned `PublicKeyCredential` (assertion) → plain dict
 * с base64url strings.
 */
export function encodeAuthenticationCredential(
  credential: PublicKeyCredential,
): Record<string, unknown> {
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: arrayBufferToBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: arrayBufferToBase64url(response.clientDataJSON),
      authenticatorData: arrayBufferToBase64url(response.authenticatorData),
      signature: arrayBufferToBase64url(response.signature),
      userHandle: response.userHandle
        ? arrayBufferToBase64url(response.userHandle)
        : null,
    },
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}

/** True если browser exposes WebAuthn API (Chromium / Firefox / Safari modern). */
export function isWebAuthnSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.PublicKeyCredential !== "undefined" &&
    typeof navigator !== "undefined" &&
    typeof navigator.credentials !== "undefined"
  );
}
