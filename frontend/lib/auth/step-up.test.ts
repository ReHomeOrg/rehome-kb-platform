import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  StepUpError,
  buildStepUpAuthUrl,
  postStepUpCallbackMessage,
  requestStepUpToken,
} from "./step-up";

// ---------------------------------------------------------------------------
// Test helpers

function _encodeJwtForTest(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }))
    .replace(/=+$/, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  const body = btoa(JSON.stringify(payload))
    .replace(/=+$/, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `${header}.${body}.signature`;
}

const ORIGIN = "http://localhost:3000";

describe("buildStepUpAuthUrl", () => {
  beforeEach(() => {
    Object.defineProperty(window, "location", {
      value: { origin: ORIGIN, hash: "" },
      writable: true,
      configurable: true,
    });
  });

  it("contains required OIDC params", () => {
    const url = buildStepUpAuthUrl("state-xyz", "nonce-abc");
    expect(url).toContain("/realms/");
    expect(url).toContain("/protocol/openid-connect/auth");
    expect(url).toContain("response_type=token+id_token");
    expect(url).toContain("acr_values=2");
    expect(url).toContain("prompt=login");
    expect(url).toContain("state=state-xyz");
    expect(url).toContain("nonce=nonce-abc");
    expect(url).toContain(
      encodeURIComponent(`${ORIGIN}/auth/step-up-callback`),
    );
  });
});

// ---------------------------------------------------------------------------
// requestStepUpToken

describe("requestStepUpToken", () => {
  let popupMock: { closed: boolean; close: () => void };
  let openSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    popupMock = { closed: false, close: vi.fn() };
    Object.defineProperty(window, "location", {
      value: { origin: ORIGIN, hash: "" },
      writable: true,
      configurable: true,
    });
    openSpy = vi
      .spyOn(window, "open")
      .mockReturnValue(popupMock as unknown as Window);
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("rejects если popup blocked", async () => {
    openSpy.mockReturnValueOnce(null);
    await expect(requestStepUpToken()).rejects.toThrow(/Popup blocked/);
  });

  it("rejects при state mismatch (CSRF guard)", async () => {
    const promise = requestStepUpToken();
    // Wait a tick for state to be stored.
    await new Promise((r) => setTimeout(r, 10));
    const wrongState = "tampered-state";
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          type: "rehome-mfa-step-up",
          accessToken: _encodeJwtForTest({ acr: "2" }),
          idToken: _encodeJwtForTest({ acr: "2" }),
          state: wrongState,
          acr: "2",
        },
        origin: ORIGIN,
      }),
    );
    await expect(promise).rejects.toThrow(/State mismatch/);
  });

  it("happy path: resolves с access token при valid acr + state + nonce", async () => {
    const promise = requestStepUpToken();
    await new Promise((r) => setTimeout(r, 10));
    const storedState = sessionStorage.getItem("mfa_step_up_state");
    const storedNonce = sessionStorage.getItem("mfa_step_up_nonce");
    expect(storedState).toBeTruthy();
    expect(storedNonce).toBeTruthy();

    const accessToken = _encodeJwtForTest({ acr: "2", sub: "user-1" });
    const idToken = _encodeJwtForTest({ acr: "2", nonce: storedNonce });
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          type: "rehome-mfa-step-up",
          accessToken,
          idToken,
          state: storedState!,
          acr: "2",
        },
        origin: ORIGIN,
      }),
    );

    const result = await promise;
    expect(result).toBe(accessToken);
    expect(popupMock.close).toHaveBeenCalled();
  });

  it("rejects при insufficient acr (e.g. acr=1)", async () => {
    const promise = requestStepUpToken();
    await new Promise((r) => setTimeout(r, 10));
    const storedState = sessionStorage.getItem("mfa_step_up_state")!;
    const accessToken = _encodeJwtForTest({ acr: "1", sub: "user-1" });
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          type: "rehome-mfa-step-up",
          accessToken,
          idToken: accessToken,
          state: storedState,
          acr: "1",
        },
        origin: ORIGIN,
      }),
    );
    await expect(promise).rejects.toThrow(/acr=1 does not match/);
  });

  it("ignores messages with wrong type", async () => {
    const promise = requestStepUpToken();
    await new Promise((r) => setTimeout(r, 10));
    const storedState = sessionStorage.getItem("mfa_step_up_state")!;
    const storedNonce = sessionStorage.getItem("mfa_step_up_nonce")!;
    // Send unrelated message — should be ignored.
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "some-other-event" },
        origin: ORIGIN,
      }),
    );
    // Then send valid one.
    const accessToken = _encodeJwtForTest({ acr: "2" });
    const idToken = _encodeJwtForTest({ acr: "2", nonce: storedNonce });
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          type: "rehome-mfa-step-up",
          accessToken,
          idToken,
          state: storedState,
          acr: "2",
        },
        origin: ORIGIN,
      }),
    );
    await expect(promise).resolves.toBe(accessToken);
  });

  it("ignores message with non-matching origin (CSRF guard)", async () => {
    const promise = requestStepUpToken();
    await new Promise((r) => setTimeout(r, 10));
    const storedState = sessionStorage.getItem("mfa_step_up_state")!;
    const storedNonce = sessionStorage.getItem("mfa_step_up_nonce")!;
    const accessToken = _encodeJwtForTest({ acr: "2" });
    const idToken = _encodeJwtForTest({ acr: "2", nonce: storedNonce });
    // Foreign origin — should be ignored by listener.
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          type: "rehome-mfa-step-up",
          accessToken,
          idToken,
          state: storedState,
          acr: "2",
        },
        origin: "https://evil.example.com",
      }),
    );
    // Now legit same-origin message — should resolve.
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          type: "rehome-mfa-step-up",
          accessToken,
          idToken,
          state: storedState,
          acr: "2",
        },
        origin: ORIGIN,
      }),
    );
    await expect(promise).resolves.toBe(accessToken);
  });

  it("rejects on popup close before MFA completion", async () => {
    const promise = requestStepUpToken();
    await new Promise((r) => setTimeout(r, 10));
    popupMock.closed = true;
    await expect(promise).rejects.toThrow(/Popup closed/);
  });

  it("rejects при empty idToken (closes nonce-bypass surface)", async () => {
    const promise = requestStepUpToken();
    await new Promise((r) => setTimeout(r, 10));
    const storedState = sessionStorage.getItem("mfa_step_up_state")!;
    const accessToken = _encodeJwtForTest({ acr: "2" });
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          type: "rehome-mfa-step-up",
          accessToken,
          idToken: "",
          state: storedState,
          acr: "2",
        },
        origin: ORIGIN,
      }),
    );
    await expect(promise).rejects.toThrow(/Missing id_token/);
  });

  it("rejects при nonce mismatch (OIDC replay guard)", async () => {
    const promise = requestStepUpToken();
    await new Promise((r) => setTimeout(r, 10));
    const storedState = sessionStorage.getItem("mfa_step_up_state")!;
    const accessToken = _encodeJwtForTest({ acr: "2", nonce: "ignored" });
    // id_token с tampered nonce → reject.
    const idTokenBadNonce = _encodeJwtForTest({ acr: "2", nonce: "tampered" });
    window.dispatchEvent(
      new MessageEvent("message", {
        data: {
          type: "rehome-mfa-step-up",
          accessToken,
          idToken: idTokenBadNonce,
          state: storedState,
          acr: "2",
        },
        origin: ORIGIN,
      }),
    );
    await expect(promise).rejects.toThrow(/Nonce mismatch/);
  });
});

// ---------------------------------------------------------------------------
// postStepUpCallbackMessage

describe("postStepUpCallbackMessage", () => {
  it("posts message to opener с extracted tokens", () => {
    const accessToken = _encodeJwtForTest({ acr: "2" });
    const idToken = _encodeJwtForTest({ acr: "2", aud: "spa" });
    const state = "test-state";
    Object.defineProperty(window, "location", {
      value: {
        origin: ORIGIN,
        hash: `#access_token=${accessToken}&id_token=${idToken}&state=${state}`,
      },
      writable: true,
      configurable: true,
    });
    const postMessageSpy = vi.fn();
    Object.defineProperty(window, "opener", {
      value: { postMessage: postMessageSpy },
      writable: true,
      configurable: true,
    });

    postStepUpCallbackMessage();

    expect(postMessageSpy).toHaveBeenCalledOnce();
    const [msg, origin] = postMessageSpy.mock.calls[0];
    expect(msg.type).toBe("rehome-mfa-step-up");
    expect(msg.accessToken).toBe(accessToken);
    expect(msg.state).toBe(state);
    expect(msg.acr).toBe("2");
    expect(origin).toBe(ORIGIN);
  });

  it("noop если нет opener", () => {
    Object.defineProperty(window, "opener", {
      value: null,
      writable: true,
      configurable: true,
    });
    // Should not throw.
    expect(() => postStepUpCallbackMessage()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// StepUpError

describe("StepUpError", () => {
  it("preserves message + name", () => {
    const err = new StepUpError("test");
    expect(err.message).toBe("test");
    expect(err.name).toBe("StepUpError");
  });
});
