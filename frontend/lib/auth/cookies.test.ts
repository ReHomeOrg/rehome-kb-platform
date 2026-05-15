import { afterAll, describe, expect, it } from "vitest";

import {
  COOKIE_OAUTH_STATE,
  COOKIE_PKCE_VERIFIER,
  COOKIE_REFRESH,
  COOKIE_SESSION,
  REFRESH_MAX_AGE_SECONDS,
  SHORT_FLOW_MAX_AGE_SECONDS,
  getCookieOptions,
} from "./cookies";

describe("auth/cookies constants", () => {
  it("named cookie constants stable", () => {
    expect(COOKIE_SESSION).toBe("kb_session");
    expect(COOKIE_REFRESH).toBe("kb_refresh");
    expect(COOKIE_PKCE_VERIFIER).toBe("kb_pkce_verifier");
    expect(COOKIE_OAUTH_STATE).toBe("kb_oauth_state");
  });

  it("short flow TTL = 5 минут", () => {
    expect(SHORT_FLOW_MAX_AGE_SECONDS).toBe(300);
  });

  it("refresh TTL = 30 дней", () => {
    expect(REFRESH_MAX_AGE_SECONDS).toBe(30 * 24 * 60 * 60);
  });
});

describe("getCookieOptions", () => {
  const originalEnv = process.env.NODE_ENV;

  afterAll(() => {
    process.env.NODE_ENV = originalEnv;
  });

  it("httpOnly=true всегда (XSS-protection)", () => {
    const opts = getCookieOptions(100);
    expect(opts.httpOnly).toBe(true);
  });

  it("sameSite=lax всегда (CSRF baseline)", () => {
    const opts = getCookieOptions(100);
    expect(opts.sameSite).toBe("lax");
  });

  it("path=/ всегда", () => {
    expect(getCookieOptions(100).path).toBe("/");
  });

  it("maxAge passthrough", () => {
    expect(getCookieOptions(42).maxAge).toBe(42);
    expect(getCookieOptions(REFRESH_MAX_AGE_SECONDS).maxAge).toBe(
      REFRESH_MAX_AGE_SECONDS,
    );
  });

  it("secure=true в production env", () => {
    process.env.NODE_ENV = "production";
    expect(getCookieOptions(100).secure).toBe(true);
  });

  it("secure=false в development / test env", () => {
    process.env.NODE_ENV = "development";
    expect(getCookieOptions(100).secure).toBe(false);
  });
});
