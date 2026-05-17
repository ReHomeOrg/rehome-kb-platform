import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  encryptBlob,
  generateSecretKey,
  toBase64,
  wrapSecretKeyForUser,
} from "@/lib/vault/crypto";
import { lock, setVaultKey } from "@/lib/vault/session";

import SecretsList from "./secrets-list";

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

async function makeVaultKey(): Promise<CryptoKey> {
  return crypto.subtle.generateKey(
    { name: "AES-GCM", length: 256 },
    false,
    ["wrapKey", "unwrapKey", "encrypt", "decrypt"],
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
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

describe("SecretsList", () => {
  it("показывает 'Vault locked' если key отсутствует", async () => {
    render(<SecretsList onCreateClick={vi.fn()} reloadToken={0} />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/locked/);
    });
  });

  it("empty state когда secrets пуст", async () => {
    const vk = await makeVaultKey();
    setVaultKey(vk);
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));
    render(<SecretsList onCreateClick={vi.fn()} reloadToken={0} />);
    await waitFor(() => {
      expect(screen.getByText(/Секретов нет/)).toBeInTheDocument();
    });
  });

  it("decrypt title локально и показать в списке", async () => {
    const vk = await makeVaultKey();
    setVaultKey(vk);
    const secretKey = await generateSecretKey();
    const titleBlob = await encryptBlob(secretKey, "Production DB");
    const wrappedKey = await wrapSecretKeyForUser(vk, secretKey);

    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          data: [
            {
              id: "s1",
              title_ciphertext_b64: toBase64(titleBlob),
              category: "password",
              owner_id: "u1",
              created_at: "2026-05-17T00:00:00Z",
              updated_at: "2026-05-17T00:00:00Z",
              expires_at: null,
              archived_at: null,
            },
          ],
        }),
      )
      // Per-row detail fetch
      .mockResolvedValueOnce(
        jsonResponse({
          id: "s1",
          title_ciphertext_b64: toBase64(titleBlob),
          category: "password",
          owner_id: "u1",
          created_at: "2026-05-17T00:00:00Z",
          updated_at: "2026-05-17T00:00:00Z",
          expires_at: null,
          archived_at: null,
          blob_ciphertext_b64: toBase64(
            await encryptBlob(secretKey, "ignored for list"),
          ),
          payload_version: 1,
          wrapped_key_b64: toBase64(wrappedKey),
          via_group_id: null,
        }),
      );

    render(<SecretsList onCreateClick={vi.fn()} reloadToken={0} />);
    await waitFor(() => {
      expect(screen.getByText("Production DB")).toBeInTheDocument();
    });
    expect(screen.getByText(/password/)).toBeInTheDocument();
  });

  it("список error на backend 500 → отображает alert", async () => {
    const vk = await makeVaultKey();
    setVaultKey(vk);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Server error" }, 500),
    );
    render(<SecretsList onCreateClick={vi.fn()} reloadToken={0} />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/500/);
    });
  });
});
