import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Fido2KeysPanel from "./fido2-keys-panel";

const fetchMock = vi.fn();
const confirmMock = vi.fn();

beforeEach(() => {
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  confirmMock.mockReset().mockReturnValue(true);
  window.confirm = confirmMock;

  Object.defineProperty(window, "PublicKeyCredential", {
    value: function () {},
    configurable: true,
    writable: true,
  });
});

afterEach(() => {
  cleanup();
});

function _listResponse(keys: Array<Partial<{ id: string; nickname: string | null; transports: string[] }>>) {
  return {
    ok: true,
    status: 200,
    text: async () =>
      JSON.stringify({
        data: keys.map((k, i) => ({
          id: k.id ?? `id-${i}`,
          nickname: k.nickname ?? null,
          created_at: "2026-05-20T12:00:00Z",
          last_used_at: null,
          transports: k.transports ?? [],
        })),
      }),
  };
}

describe("Fido2KeysPanel", () => {
  it("показывает пустое состояние когда нет ключей", async () => {
    fetchMock.mockResolvedValueOnce(_listResponse([]));
    render(<Fido2KeysPanel />);
    await waitFor(() => {
      expect(screen.getByText(/Пока нет зарегистрированных ключей/i)).toBeDefined();
    });
  });

  it("отображает список ключей с metadata", async () => {
    fetchMock.mockResolvedValueOnce(
      _listResponse([{ id: "key-1", nickname: "YubiKey", transports: ["usb", "nfc"] }]),
    );
    render(<Fido2KeysPanel />);
    await waitFor(() => {
      expect(screen.getByText("YubiKey")).toBeDefined();
    });
    expect(screen.getByText(/usb, nfc/)).toBeDefined();
  });

  it("показывает 'Добавить ключ' если under cap, скрывает на cap", async () => {
    fetchMock.mockResolvedValueOnce(
      _listResponse(Array.from({ length: 5 }, (_, i) => ({ id: `k${i}` }))),
    );
    render(<Fido2KeysPanel />);
    await waitFor(() => {
      expect(screen.getByText(/Достигнут лимит/i)).toBeDefined();
    });
    expect(screen.queryByText(/^Добавить ключ$/)).toBeNull();
  });

  it("revoke confirmed → DELETE + remove from list", async () => {
    fetchMock
      .mockResolvedValueOnce(_listResponse([{ id: "key-1", nickname: "YubiKey" }]))
      .mockResolvedValueOnce({ ok: true, status: 204, text: async () => "" });
    render(<Fido2KeysPanel />);
    await waitFor(() => {
      expect(screen.getByText("YubiKey")).toBeDefined();
    });
    fireEvent.click(screen.getByText("Удалить"));
    await waitFor(() => {
      expect(screen.queryByText("YubiKey")).toBeNull();
    });
    expect(confirmMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[1][1].method).toBe("DELETE");
  });

  it("revoke cancelled → no DELETE call", async () => {
    confirmMock.mockReturnValue(false);
    fetchMock.mockResolvedValueOnce(
      _listResponse([{ id: "key-1", nickname: "YubiKey" }]),
    );
    render(<Fido2KeysPanel />);
    await waitFor(() => {
      expect(screen.getByText("YubiKey")).toBeDefined();
    });
    fireEvent.click(screen.getByText("Удалить"));
    expect(fetchMock.mock.calls).toHaveLength(1); // только initial list, no DELETE
  });

  it("error на list → error message + не падает", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ detail: "boom" }),
      text: async () => JSON.stringify({ detail: "boom" }),
    });
    render(<Fido2KeysPanel />);
    await waitFor(() => {
      expect(screen.getByText(/500/)).toBeDefined();
    });
  });
});
