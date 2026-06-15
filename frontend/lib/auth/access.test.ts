import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getSessionAccess } from "./access";

const cookieStoreMock = {
  get: vi.fn<(name: string) => { value: string } | undefined>(),
};

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => cookieStoreMock),
}));

/** Собирает «токен» с переданным payload (подпись не важна — не верифицируем). */
function fakeJwt(payload: Record<string, unknown>): string {
  const b64url = (obj: unknown): string =>
    Buffer.from(JSON.stringify(obj))
      .toString("base64")
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  return `${b64url({ alg: "RS256" })}.${b64url(payload)}.sig`;
}

beforeEach(() => {
  cookieStoreMock.get.mockReset();
});
afterEach(() => {
  vi.clearAllMocks();
});

describe("getSessionAccess", () => {
  it("нет cookie → не залогинен, не staff_admin", async () => {
    cookieStoreMock.get.mockReturnValue(undefined);
    const access = await getSessionAccess();
    expect(access).toEqual({ isLoggedIn: false, isStaffAdmin: false });
  });

  it("cookie без роли staff_admin → залогинен, но не staff_admin", async () => {
    cookieStoreMock.get.mockReturnValue({
      value: fakeJwt({ realm_access: { roles: ["tenant"] } }),
    });
    const access = await getSessionAccess();
    expect(access).toEqual({ isLoggedIn: true, isStaffAdmin: false });
  });

  it("cookie с ролью staff_admin → staff_admin", async () => {
    cookieStoreMock.get.mockReturnValue({
      value: fakeJwt({ realm_access: { roles: ["staff_admin", "staff_hr"] } }),
    });
    const access = await getSessionAccess();
    expect(access).toEqual({ isLoggedIn: true, isStaffAdmin: true });
  });

  it("malformed token → залогинен (cookie есть), но не staff_admin", async () => {
    cookieStoreMock.get.mockReturnValue({ value: "not-a-jwt" });
    const access = await getSessionAccess();
    expect(access).toEqual({ isLoggedIn: true, isStaffAdmin: false });
  });
});
