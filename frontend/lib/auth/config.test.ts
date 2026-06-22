import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildIssuerUrl,
  getAuthConfig,
  getRehomeIdpHint,
  isAllowedIdpHint,
} from "./config";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("getAuthConfig", () => {
  it("returns defaults when env not set", () => {
    vi.stubEnv("NEXT_PUBLIC_KC_URL", undefined as unknown as string);
    vi.stubEnv("NEXT_PUBLIC_KC_REALM", undefined as unknown as string);
    vi.stubEnv("NEXT_PUBLIC_KC_CLIENT_ID", undefined as unknown as string);
    const cfg = getAuthConfig();
    expect(cfg.keycloakUrl).toBe("http://localhost:8080");
    expect(cfg.realm).toBe("rehome");
    expect(cfg.clientId).toBe("rehome-web-spa");
    expect(cfg.redirectUri).toBe(
      "http://localhost:3000/api/auth/callback/keycloak",
    );
  });

  it("reads from env when set", () => {
    vi.stubEnv("NEXT_PUBLIC_KC_URL", "https://kc.example.com");
    vi.stubEnv("NEXT_PUBLIC_KC_REALM", "prod");
    vi.stubEnv("NEXT_PUBLIC_KC_CLIENT_ID", "spa-prod");
    const cfg = getAuthConfig();
    expect(cfg.keycloakUrl).toBe("https://kc.example.com");
    expect(cfg.realm).toBe("prod");
    expect(cfg.clientId).toBe("spa-prod");
  });
});

describe("isAllowedIdpHint", () => {
  it("accepts allowlisted alias", () => {
    expect(isAllowedIdpHint("rehome")).toBe(true);
  });

  it("rejects unknown/empty/null (анти-param-injection)", () => {
    expect(isAllowedIdpHint("evil")).toBe(false);
    expect(isAllowedIdpHint("")).toBe(false);
    expect(isAllowedIdpHint(null)).toBe(false);
    expect(isAllowedIdpHint(undefined)).toBe(false);
  });
});

describe("getRehomeIdpHint", () => {
  it("returns alias when env set to allowlisted value", () => {
    vi.stubEnv("NEXT_PUBLIC_REHOME_IDP_HINT", "rehome");
    expect(getRehomeIdpHint()).toBe("rehome");
  });

  it("returns null when env unset (прод-сборка — кнопки нет)", () => {
    vi.stubEnv("NEXT_PUBLIC_REHOME_IDP_HINT", undefined as unknown as string);
    expect(getRehomeIdpHint()).toBeNull();
  });

  it("returns null when env set to non-allowlisted value", () => {
    vi.stubEnv("NEXT_PUBLIC_REHOME_IDP_HINT", "evil");
    expect(getRehomeIdpHint()).toBeNull();
  });
});

describe("buildIssuerUrl", () => {
  it("concatenates keycloakUrl + realm path", () => {
    const url = buildIssuerUrl({
      keycloakUrl: "http://localhost:8080",
      realm: "rehome",
      clientId: "spa",
      redirectUri: "x",
      postLogoutRedirectUri: "y",
    });
    expect(url).toBe("http://localhost:8080/realms/rehome");
  });
});
