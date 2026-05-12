import { describe, it, expect } from "vitest";

import { generateState } from "./state";

describe("generateState", () => {
  it("returns 43-char base64url-encoded random string", () => {
    const state = generateState();
    expect(state).toMatch(/^[A-Za-z0-9\-_]+$/);
    expect(state.length).toBe(43); // 32 bytes → base64url ~43 chars
  });

  it("produces unique values (no collisions in 1000 iterations)", () => {
    const set = new Set<string>();
    for (let i = 0; i < 1000; i++) {
      set.add(generateState());
    }
    expect(set.size).toBe(1000);
  });
});
