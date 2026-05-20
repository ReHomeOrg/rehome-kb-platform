import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Fido2RegisterForm from "./fido2-register-form";

const fetchMock = vi.fn();
const navigatorCreateMock = vi.fn();

beforeEach(() => {
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  navigatorCreateMock.mockReset();

  // Stub WebAuthn API on window.
  Object.defineProperty(window, "PublicKeyCredential", {
    value: function () {},
    configurable: true,
    writable: true,
  });
  Object.defineProperty(navigator, "credentials", {
    value: { create: navigatorCreateMock, get: vi.fn() },
    configurable: true,
    writable: true,
  });
});

afterEach(() => {
  cleanup();
});

function _b64url(bytes: Uint8Array): string {
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function _registrationOptions(): Record<string, unknown> {
  return {
    challenge: _b64url(new Uint8Array([1, 2, 3])),
    rp: { id: "localhost", name: "Test" },
    user: {
      id: _b64url(new TextEncoder().encode("user-uuid")),
      name: "alice",
      displayName: "alice",
    },
    pubKeyCredParams: [{ type: "public-key", alg: -7 }],
    excludeCredentials: [],
  };
}

function _makeFakeCredential(): PublicKeyCredential {
  return {
    id: "cred-id",
    rawId: new Uint8Array([10, 20, 30]).buffer,
    type: "public-key",
    response: {
      clientDataJSON: new TextEncoder().encode('{"challenge":"abc"}').buffer,
      attestationObject: new Uint8Array([0xaa]).buffer,
      getTransports: () => ["usb"],
    },
    getClientExtensionResults: () => ({}),
  } as unknown as PublicKeyCredential;
}

describe("Fido2RegisterForm", () => {
  it("браузер без WebAuthn показывает warning", () => {
    Object.defineProperty(window, "PublicKeyCredential", {
      value: undefined,
      configurable: true,
      writable: true,
    });
    render(<Fido2RegisterForm onSuccess={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText(/не поддерживает WebAuthn/i)).toBeDefined();
  });

  it("happy path: begin → create → complete → onSuccess", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ options: _registrationOptions() }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 201,
        text: async () =>
          JSON.stringify({
            id: "cred-uuid",
            nickname: "YubiKey",
            created_at: "2026-05-20T12:00:00Z",
            last_used_at: null,
            transports: ["usb"],
          }),
      });
    navigatorCreateMock.mockResolvedValueOnce(_makeFakeCredential());

    const onSuccess = vi.fn();
    render(<Fido2RegisterForm onSuccess={onSuccess} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/YubiKey/), {
      target: { value: "YubiKey" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
    const cred = onSuccess.mock.calls[0][0];
    expect(cred.id).toBe("cred-uuid");
    expect(cred.nickname).toBe("YubiKey");

    // Verified that complete-PR shape forward'ит nickname.
    const completeBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(completeBody.nickname).toBe("YubiKey");
    expect(completeBody.credential.id).toBe("cred-id");
  });

  it("409 с backend → user-friendly cap-reached message", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ options: _registrationOptions() }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ detail: "Max 5 FIDO2 keys per user" }),
        text: async () => JSON.stringify({ detail: "Max 5 FIDO2 keys per user" }),
      });
    navigatorCreateMock.mockResolvedValueOnce(_makeFakeCredential());

    render(<Fido2RegisterForm onSuccess={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));

    await waitFor(() => {
      expect(screen.getByText(/лимит ключей/i)).toBeDefined();
    });
  });

  it("user отменил authenticator prompt → friendly error", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ options: _registrationOptions() }),
    });
    navigatorCreateMock.mockRejectedValueOnce(
      new DOMException("user cancelled", "NotAllowedError"),
    );

    render(<Fido2RegisterForm onSuccess={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Зарегистрировать" }));

    await waitFor(() => {
      expect(screen.getByText(/отменена/i)).toBeDefined();
    });
  });

  it("cancel button calls onCancel", () => {
    const onCancel = vi.fn();
    render(<Fido2RegisterForm onSuccess={vi.fn()} onCancel={onCancel} />);
    fireEvent.click(screen.getByText(/^Отмена$/));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
