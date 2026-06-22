/**
 * Keycloak OAuth 2.0 client helpers.
 *
 * Authorization Code Grant + PKCE (RFC 6749 §4.1, RFC 7636).
 */

import { AuthConfig, buildIssuerUrl } from "./config";

export interface TokenResponse {
  access_token: string;
  expires_in: number;
  token_type: "Bearer";
  refresh_token?: string;
  id_token?: string;
  scope?: string;
}

export interface AuthorizationParams {
  state: string;
  codeChallenge: string;
  /**
   * Optional alias upstream-IdP (`kc_idp_hint`): Keycloak сразу редиректит на
   * этот brokered IdP, минуя свою форму логина (silent SSO при активной сессии).
   */
  idpHint?: string;
}

/**
 * Build URL для редиректа на Keycloak /auth (Authorization endpoint).
 */
export function buildAuthorizationUrl(
  config: AuthConfig,
  params: AuthorizationParams,
): string {
  const issuer = buildIssuerUrl(config);
  const queryParams = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    response_type: "code",
    scope: "openid",
    state: params.state,
    code_challenge: params.codeChallenge,
    code_challenge_method: "S256",
  });
  if (params.idpHint) {
    queryParams.set("kc_idp_hint", params.idpHint);
  }
  return `${issuer}/protocol/openid-connect/auth?${queryParams.toString()}`;
}

/**
 * Exchange authorization code for tokens via Keycloak /token endpoint.
 *
 * Throws Error при non-200 ответе. Сообщение error содержит ТОЛЬКО `error`
 * code, не `error_description` — последний может содержать user-data.
 */
export async function exchangeCodeForToken(
  config: AuthConfig,
  code: string,
  codeVerifier: string,
): Promise<TokenResponse> {
  const issuer = buildIssuerUrl(config);
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    code_verifier: codeVerifier,
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
  });

  const response = await fetch(`${issuer}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
    cache: "no-store",
  });

  if (!response.ok) {
    const errorBody = (await response.json().catch(() => ({}))) as {
      error?: string;
    };
    throw new Error(
      `Token exchange failed: ${response.status} ${errorBody.error ?? "unknown_error"}`,
    );
  }

  const data = (await response.json()) as TokenResponse;
  if (typeof data.access_token !== "string" || data.access_token.length === 0) {
    throw new Error("Token exchange returned no access_token");
  }
  return data;
}

/**
 * Refresh access_token через Keycloak `/token` endpoint
 * (`grant_type=refresh_token`). Returns same TokenResponse shape —
 * новый access_token + (optionally) refresh_token rotation.
 *
 * Keycloak по default rotate'ит refresh token при каждом use'е — caller
 * должен persist'ить новый `refresh_token` если он пришёл.
 *
 * Throws Error при 4xx / 5xx — caller forces re-login.
 */
export async function refreshAccessToken(
  config: AuthConfig,
  refreshToken: string,
): Promise<TokenResponse> {
  const issuer = buildIssuerUrl(config);
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    refresh_token: refreshToken,
    client_id: config.clientId,
  });
  const response = await fetch(`${issuer}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
    cache: "no-store",
  });
  if (!response.ok) {
    const errorBody = (await response.json().catch(() => ({}))) as {
      error?: string;
    };
    throw new Error(
      `Refresh failed: ${response.status} ${errorBody.error ?? "unknown_error"}`,
    );
  }
  const data = (await response.json()) as TokenResponse;
  if (typeof data.access_token !== "string" || data.access_token.length === 0) {
    throw new Error("Refresh returned no access_token");
  }
  return data;
}

/**
 * Build URL для Keycloak /logout (frontchannel logout).
 *
 * См. https://www.keycloak.org/docs/latest/securing_apps/#logout
 */
export function buildLogoutUrl(config: AuthConfig, idToken?: string): string {
  const issuer = buildIssuerUrl(config);
  const params = new URLSearchParams({
    post_logout_redirect_uri: config.postLogoutRedirectUri,
    client_id: config.clientId,
  });
  if (idToken) {
    params.set("id_token_hint", idToken);
  }
  return `${issuer}/protocol/openid-connect/logout?${params.toString()}`;
}
