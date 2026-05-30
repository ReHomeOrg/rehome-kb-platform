import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { base32Decode, totpCode } from "@/lib/vault/totp";
import { lock, setVaultKey } from "@/lib/vault/session";

import TotpSetupForm from "./totp-setup-form";

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

async function makeVaultKey(): Promise<CryptoKey> {
  return crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    false,
    ["wrapKey", "unwrapKey", "encrypt", "decrypt"],
  );
}

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  lock();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
  lock();
});

describe("TotpSetupForm", () => {
  it("показывает secret + otpauth URI после mount", async () => {
    render(
      <TotpSetupForm
        accountLabel="alice"
        onCancel={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    const secret = await screen.findByTestId("totp-secret");
    expect(secret.textContent ?? "").toMatch(/^[A-Z2-7]{32}$/);
    const uri = await screen.findByTestId("totp-uri");
    expect(uri.textContent ?? "").toMatch(/^otpauth:\/\/totp\/alice/);
  });

  it("invalid code → local error без fetch", async () => {
    render(
      <TotpSetupForm
        accountLabel="alice"
        onCancel={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    await screen.findByTestId("totp-secret");
    fireEvent.change(screen.getByLabelText(/Код из приложения/), {
      target: { value: "abc" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Подключить 2FA/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/6 цифр/);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("wrong code → local error 'не подошёл'", async () => {
    render(
      <TotpSetupForm
        accountLabel="alice"
        onCancel={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    await screen.findByTestId("totp-secret");
    fireEvent.change(screen.getByLabelText(/Код из приложения/), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Подключить 2FA/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/не подошёл/);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("vault locked → local error", async () => {
    render(
      <TotpSetupForm
        accountLabel="alice"
        onCancel={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    const secretEl = await screen.findByTestId("totp-secret");
    const secret = base32Decode(secretEl.textContent ?? "");
    const correctCode = await totpCode(
      secret,
      Math.floor(Date.now() / 1000),
    );
    // vault locked (default — lock() в beforeEach).
    fireEvent.change(screen.getByLabelText(/Код из приложения/), {
      target: { value: correctCode },
    });
    fireEvent.click(screen.getByRole("button", { name: /Подключить 2FA/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/locked/);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("happy path → encrypts secret + POSTs к /vault/totp/setup", async () => {
    const vaultKey = await makeVaultKey();
    setVaultKey(vaultKey);
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ is_setup: true, has_totp: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const onSuccess = vi.fn();
    render(
      <TotpSetupForm
        accountLabel="alice"
        onCancel={vi.fn()}
        onSuccess={onSuccess}
      />,
    );
    const secretEl = await screen.findByTestId("totp-secret");
    const secret = base32Decode(secretEl.textContent ?? "");
    const correctCode = await totpCode(
      secret,
      Math.floor(Date.now() / 1000),
    );
    fireEvent.change(screen.getByLabelText(/Код из приложения/), {
      target: { value: correctCode },
    });
    fireEvent.click(screen.getByRole("button", { name: /Подключить 2FA/ }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/kb/api/v1/vault/totp/setup",
        expect.objectContaining({ method: "POST" }),
      );
    });
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as RequestInit).body as string,
    );
    expect(typeof body.totp_secret_encrypted_b64).toBe("string");
    expect(body.totp_secret_encrypted_b64.length).toBeGreaterThan(20);
    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  it("Отмена → onCancel", async () => {
    const onCancel = vi.fn();
    render(
      <TotpSetupForm
        accountLabel="alice"
        onCancel={onCancel}
        onSuccess={vi.fn()}
      />,
    );
    await screen.findByTestId("totp-secret");
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("показывает QR-код после mount с корректным alt-текстом", async () => {
    render(
      <TotpSetupForm
        accountLabel="alice"
        onCancel={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    const qr = await screen.findByTestId("totp-qr");
    expect(qr.tagName).toBe("IMG");
    expect(qr.getAttribute("alt")).toMatch(/QR-код для otpauth URI/);
    expect(qr.getAttribute("src") ?? "").toMatch(/^data:image\/png;base64,/);
  });

  it("если QR не сгенерирован — секрет и URI остаются доступными", async () => {
    // Mock'аем wrapper на reject, чтобы симулировать ошибку рендера QR.
    const totpModule = await import("@/lib/vault/totp");
    const spy = vi
      .spyOn(totpModule, "otpauthQrDataUrl")
      .mockRejectedValue(new Error("simulated render fail"));

    render(
      <TotpSetupForm
        accountLabel="alice"
        onCancel={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    // Secret и URI должны быть видны (graceful fallback).
    await screen.findByTestId("totp-secret");
    expect(await screen.findByTestId("totp-uri")).toBeInTheDocument();
    expect(screen.queryByTestId("totp-qr")).not.toBeInTheDocument();

    spy.mockRestore();
  });
});
