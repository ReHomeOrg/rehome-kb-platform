/**
 * Tests for Keycloak client helpers.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildAuthorizationUrl,
  buildLogoutUrl,
  exchangeCodeForToken,
} from "./keycloak";
import type { AuthConfig } from "./config";

const cfg: AuthConfig = {
  keycloakUrl: "http://localhost:8080",
  realm: "rehome",
  clientId: "rehome-web-spa",
  redirectUri: "http://localhost:3000/api/auth/callback/keycloak",
  postLogoutRedirectUri: "http://localhost:3000/",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("buildAuthorizationUrl", () => {
  it("contains all required OAuth + PKCE params", () => {
    const url = buildAuthorizationUrl(cfg, {
      state: "test-state",
      codeChallenge: "test-challenge",
    });
    const parsed = new URL(url);
    expect(parsed.origin).toBe("http://localhost:8080");
    expect(parsed.pathname).toBe("/realms/rehome/protocol/openid-connect/auth");
    expect(parsed.searchParams.get("client_id")).toBe("rehome-web-spa");
    expect(parsed.searchParams.get("redirect_uri")).toBe(
      "http://localhost:3000/api/auth/callback/keycloak",
    );
    expect(parsed.searchParams.get("response_type")).toBe("code");
    expect(parsed.searchParams.get("scope")).toBe("openid");
    expect(parsed.searchParams.get("state")).toBe("test-state");
    expect(parsed.searchParams.get("code_challenge")).toBe("test-challenge");
    expect(parsed.searchParams.get("code_challenge_method")).toBe("S256");
  });

  it("omits kc_idp_hint when idpHint not provided", () => {
    const url = buildAuthorizationUrl(cfg, {
      state: "s",
      codeChallenge: "c",
    });
    expect(new URL(url).searchParams.has("kc_idp_hint")).toBe(false);
  });

  it("adds kc_idp_hint when idpHint provided (brokered-login)", () => {
    const url = buildAuthorizationUrl(cfg, {
      state: "s",
      codeChallenge: "c",
      idpHint: "rehome",
    });
    expect(new URL(url).searchParams.get("kc_idp_hint")).toBe("rehome");
  });
});

describe("exchangeCodeForToken", () => {
  it("returns parsed token on 200", async () => {
    const fetchMock = vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          access_token: "test-access",
          expires_in: 3600,
          token_type: "Bearer",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    const result = await exchangeCodeForToken(cfg, "test-code", "test-verifier");
    expect(result.access_token).toBe("test-access");
    expect(result.expires_in).toBe(3600);
    expect(fetchMock).toHaveBeenCalledOnce();
    const [calledUrl, calledInit] = fetchMock.mock.calls[0];
    expect(calledUrl).toBe(
      "http://localhost:8080/realms/rehome/protocol/openid-connect/token",
    );
    expect(calledInit?.method).toBe("POST");
  });

  it("throws with status + error code on 400, NO error_description", async () => {
    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: "invalid_grant",
          error_description: "sensitive user data here",
        }),
        { status: 400 },
      ),
    );
    await expect(
      exchangeCodeForToken(cfg, "bad-code", "test-verifier"),
    ).rejects.toThrow(/invalid_grant/);
    // error_description НЕ ДОЛЖЕН быть в Error message (защита ПДн).
    await expect(
      exchangeCodeForToken(cfg, "bad-code", "test-verifier").catch((e) =>
        Promise.reject(e),
      ),
    ).rejects.toThrow(/^(?!.*sensitive user data).*/);
  });

  it("throws when access_token missing", async () => {
    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ expires_in: 3600 }), { status: 200 }),
    );
    await expect(
      exchangeCodeForToken(cfg, "test-code", "test-verifier"),
    ).rejects.toThrow(/no access_token/);
  });
});

describe("buildLogoutUrl", () => {
  it("contains post_logout_redirect_uri and client_id", () => {
    const url = buildLogoutUrl(cfg);
    const parsed = new URL(url);
    expect(parsed.pathname).toBe(
      "/realms/rehome/protocol/openid-connect/logout",
    );
    expect(parsed.searchParams.get("post_logout_redirect_uri")).toBe(
      "http://localhost:3000/",
    );
    expect(parsed.searchParams.get("client_id")).toBe("rehome-web-spa");
  });

  it("adds id_token_hint when provided", () => {
    const url = buildLogoutUrl(cfg, "test-id-token");
    expect(new URL(url).searchParams.get("id_token_hint")).toBe("test-id-token");
  });
});
