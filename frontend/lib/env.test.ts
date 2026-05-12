import { afterEach, describe, expect, it } from "vitest";

import { getBackendBaseUrl } from "./env";

const ORIGINAL = process.env.BACKEND_BASE_URL;

afterEach(() => {
  if (ORIGINAL === undefined) {
    delete process.env.BACKEND_BASE_URL;
  } else {
    process.env.BACKEND_BASE_URL = ORIGINAL;
  }
});

describe("getBackendBaseUrl", () => {
  it("returns default localhost when env missing", () => {
    delete process.env.BACKEND_BASE_URL;
    expect(getBackendBaseUrl()).toBe("http://localhost:8000");
  });

  it("returns provided env value", () => {
    process.env.BACKEND_BASE_URL = "https://api.rehome.one";
    expect(getBackendBaseUrl()).toBe("https://api.rehome.one");
  });

  it("strips trailing slash", () => {
    process.env.BACKEND_BASE_URL = "https://api.rehome.one/";
    expect(getBackendBaseUrl()).toBe("https://api.rehome.one");
  });

  it("strips multiple trailing slashes", () => {
    process.env.BACKEND_BASE_URL = "https://api.rehome.one///";
    expect(getBackendBaseUrl()).toBe("https://api.rehome.one");
  });

  it("throws on invalid URL", () => {
    process.env.BACKEND_BASE_URL = "not-a-url";
    expect(() => getBackendBaseUrl()).toThrow(/не является валидным URL/);
  });
});
