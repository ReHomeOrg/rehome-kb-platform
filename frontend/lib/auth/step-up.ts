/**
 * Keycloak step-up MFA token acquisition (RFC 9470 / ADR-0019 §«MFA»).
 *
 * Flow:
 * 1. Open Keycloak в popup window с `acr_values=2&prompt=login`.
 * 2. User completes MFA challenge в Keycloak (TOTP / FIDO2).
 * 3. Keycloak redirects popup back to `/auth/step-up-callback` с
 *    URL fragment containing `access_token` + `id_token`.
 * 4. Callback page parses fragment, posts message to `window.opener`.
 * 5. This hook resolves Promise with token; original action retries
 *    с X-MFA-Token header.
 *
 * Security:
 * - `state` param (CSRF protection) generated + stored в sessionStorage,
 *   validated on message receipt.
 * - postMessage origin checked (same-origin).
 * - Token's `acr` claim decoded + verified (Keycloak realm default `2`,
 *   override через NEXT_PUBLIC_KC_REQUIRED_ACR).
 * - Promise rejects на timeout (5 min) / popup close / state mismatch /
 *   insufficient acr.
 *
 * Production prerequisites (Keycloak realm config):
 * - SPA client `rehome-web-spa` allows `Implicit Flow` (response_type=
 *   token id_token).
 * - `redirect_uri` `<origin>/auth/step-up-callback` whitelisted в client'е.
 * - MFA challenge configured (TOTP / FIDO2 required для acr=2 binding).
 */

import { buildIssuerUrl, getAuthConfig } from "./config";
import { decodeJwtClaims } from "./jwt";

const POPUP_TIMEOUT_MS = 5 * 60 * 1000; // 5 min — matches typical MFA UX.
const STATE_SESSION_KEY = "mfa_step_up_state";
const NONCE_SESSION_KEY = "mfa_step_up_nonce";

export class StepUpError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StepUpError";
  }
}

export interface StepUpMessage {
  type: "rehome-mfa-step-up";
  accessToken: string;
  idToken: string;
  state: string;
  acr: string | null;
}

function randomHex(bytes: number): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return Array.from(buf)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function decodeOrThrow(token: string): {
  acr?: string | number;
  nonce?: string;
} {
  const claims = decodeJwtClaims(token);
  if (claims === null) throw new StepUpError("Malformed JWT");
  return claims;
}

function getRequiredAcr(): string {
  return process.env.NEXT_PUBLIC_KC_REQUIRED_ACR ?? "2";
}

/**
 * Construct Keycloak `/auth` URL для step-up. Implicit flow (response_type=
 * token id_token) — popup получает tokens напрямую в URL fragment без
 * exchange'а через backend.
 */
export function buildStepUpAuthUrl(state: string, nonce: string): string {
  const config = getAuthConfig();
  const redirectUri = `${window.location.origin}/auth/step-up-callback`;
  const params = new URLSearchParams({
    client_id: config.clientId,
    response_type: "token id_token",
    scope: "openid",
    redirect_uri: redirectUri,
    state,
    nonce,
    acr_values: getRequiredAcr(),
    prompt: "login", // force re-auth so user actually does MFA challenge.
  });
  return `${buildIssuerUrl(config)}/protocol/openid-connect/auth?${params.toString()}`;
}

/**
 * Open step-up popup + resolve с access_token after callback posts message.
 *
 * @throws StepUpError on timeout, popup close, state mismatch, acr below
 *   threshold, или browser blocking popup.
 */
export async function requestStepUpToken(): Promise<string> {
  if (typeof window === "undefined") {
    throw new StepUpError("Step-up MFA requires browser context");
  }

  const state = randomHex(16);
  const nonce = randomHex(16);
  sessionStorage.setItem(STATE_SESSION_KEY, state);
  sessionStorage.setItem(NONCE_SESSION_KEY, nonce);

  const url = buildStepUpAuthUrl(state, nonce);
  const popup = window.open(url, "rehome_mfa_step_up", "width=500,height=700");
  if (!popup) {
    sessionStorage.removeItem(STATE_SESSION_KEY);
    sessionStorage.removeItem(NONCE_SESSION_KEY);
    throw new StepUpError(
      "Popup blocked. Разрешите всплывающие окна для этого сайта.",
    );
  }

  return new Promise<string>((resolve, reject) => {
    let resolved = false;

    const cleanup = (): void => {
      window.removeEventListener("message", onMessage);
      clearInterval(closeWatcher);
      clearTimeout(timeoutHandle);
      sessionStorage.removeItem(STATE_SESSION_KEY);
      sessionStorage.removeItem(NONCE_SESSION_KEY);
    };

    const onMessage = (event: MessageEvent): void => {
      if (event.origin !== window.location.origin) return;
      const data = event.data as Partial<StepUpMessage> | null;
      if (!data || data.type !== "rehome-mfa-step-up") return;

      if (data.state !== state) {
        resolved = true;
        cleanup();
        reject(new StepUpError("State mismatch (CSRF guard)"));
        return;
      }
      if (!data.accessToken) {
        resolved = true;
        cleanup();
        reject(new StepUpError("Callback did not return access_token"));
        return;
      }

      // Verify acr in access_token matches requirement + nonce in id_token
      // matches stored value (OIDC replay protection).
      try {
        const accessClaims = decodeOrThrow(data.accessToken);
        const required = getRequiredAcr();
        if (accessClaims.acr === undefined || String(accessClaims.acr) !== required) {
          resolved = true;
          cleanup();
          reject(
            new StepUpError(
              `Token acr=${String(accessClaims.acr)} does not match required ${required}`,
            ),
          );
          return;
        }
        // OIDC nonce check — defense against id_token replay. SPA requests
        // `response_type=token id_token`, so missing/empty id_token is a
        // protocol violation; reject hard (closes nonce-bypass surface).
        if (!data.idToken) {
          resolved = true;
          cleanup();
          reject(
            new StepUpError(
              "Missing id_token — protocol expected token+id_token response",
            ),
          );
          return;
        }
        const idClaims = decodeOrThrow(data.idToken);
        if (idClaims.nonce !== nonce) {
          resolved = true;
          cleanup();
          reject(new StepUpError("Nonce mismatch (OIDC replay guard)"));
          return;
        }
      } catch (err) {
        resolved = true;
        cleanup();
        reject(
          err instanceof StepUpError
            ? err
            : new StepUpError(`Token decode failed: ${String(err)}`),
        );
        return;
      }

      resolved = true;
      cleanup();
      try {
        popup.close();
      } catch {
        // Popup может already be closed; ignore.
      }
      resolve(data.accessToken);
    };

    const closeWatcher = setInterval(() => {
      if (popup.closed && !resolved) {
        resolved = true;
        cleanup();
        reject(new StepUpError("Popup closed before MFA completion"));
      }
    }, 500);

    const timeoutHandle = setTimeout(() => {
      if (resolved) return;
      resolved = true;
      cleanup();
      try {
        popup.close();
      } catch {
        // ignore
      }
      reject(new StepUpError("Step-up timeout (5 min)"));
    }, POPUP_TIMEOUT_MS);

    window.addEventListener("message", onMessage);
  });
}

/**
 * Helper для popup callback page: extracts URL fragment, posts message
 * to opener. Идемпотентно — callback page вызывает в useEffect.
 */
export function postStepUpCallbackMessage(): void {
  if (typeof window === "undefined" || !window.opener) return;

  const fragment = window.location.hash.replace(/^#/, "");
  const params = new URLSearchParams(fragment);
  const accessToken = params.get("access_token") ?? "";
  const idToken = params.get("id_token") ?? "";
  const state = params.get("state") ?? "";

  let acr: string | null = null;
  if (idToken) {
    const claims = decodeJwtClaims(idToken);
    acr = claims?.acr === undefined || claims.acr === null ? null : String(claims.acr);
  }

  const msg: StepUpMessage = {
    type: "rehome-mfa-step-up",
    accessToken,
    idToken,
    state,
    acr,
  };
  window.opener.postMessage(msg, window.location.origin);
}
