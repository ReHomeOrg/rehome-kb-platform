/**
 * Auth configuration — env-driven.
 *
 * Все значения берутся из process.env с дефолтами под local-dev.
 * Production требует явных значений (нет fallback на localhost).
 */

export interface AuthConfig {
  /** Keycloak base URL (public, без `/realms/...`). */
  readonly keycloakUrl: string;
  /** Realm name. */
  readonly realm: string;
  /** OAuth client_id для SPA-клиента. */
  readonly clientId: string;
  /** Callback redirect URI — должен совпадать с redirectUris в realm config (ADR-0007). */
  readonly redirectUri: string;
  /** Logout post-redirect URI (куда уйти после logout у Keycloak). */
  readonly postLogoutRedirectUri: string;
}

export function getAuthConfig(): AuthConfig {
  return {
    keycloakUrl: process.env.NEXT_PUBLIC_KC_URL ?? "http://localhost:8080",
    realm: process.env.NEXT_PUBLIC_KC_REALM ?? "rehome",
    clientId: process.env.NEXT_PUBLIC_KC_CLIENT_ID ?? "rehome-web-spa",
    redirectUri:
      process.env.KC_REDIRECT_URI ??
      "http://localhost:3000/api/auth/callback/keycloak",
    postLogoutRedirectUri:
      process.env.KC_POST_LOGOUT_URI ?? "http://localhost:3000/",
  };
}

export function buildIssuerUrl(config: AuthConfig): string {
  return `${config.keycloakUrl}/realms/${config.realm}`;
}
