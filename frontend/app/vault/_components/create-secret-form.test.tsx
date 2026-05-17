import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  decryptBlob,
  fromBase64,
  unwrapSecretKeyForUser,
} from "@/lib/vault/crypto";
import { lock, setVaultKey } from "@/lib/vault/session";

import CreateSecretForm from "./create-secret-form";

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

describe("CreateSecretForm", () => {
  it("ошибка если vault locked", async () => {
    const onCancel = vi.fn();
    const onSuccess = vi.fn();
    render(
      <CreateSecretForm
        userId="user-1"
        onCancel={onCancel}
        onSuccess={onSuccess}
      />,
    );
    fireEvent.change(screen.getByLabelText(/Title/), {
      target: { value: "Test" },
    });
    fireEvent.change(screen.getByLabelText(/Содержимое/), {
      target: { value: "secret data" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/locked/);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("happy path — encrypts blob, self-wraps, POSTs encrypted body", async () => {
    const vaultKey = await makeVaultKey();
    setVaultKey(vaultKey);

    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ id: "secret-1", payload_version: 1 }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    const onSuccess = vi.fn();
    render(
      <CreateSecretForm
        userId="user-abc"
        onCancel={vi.fn()}
        onSuccess={onSuccess}
      />,
    );
    fireEvent.change(screen.getByLabelText(/Title/), {
      target: { value: "Production DB" },
    });
    fireEvent.change(screen.getByLabelText(/Содержимое/), {
      target: { value: "postgres://user:pass@host" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/kb/api/v1/vault/secrets",
        expect.objectContaining({ method: "POST" }),
      );
    });
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as RequestInit).body as string,
    );
    expect(body.category).toBe("password");
    expect(body.wraps).toHaveLength(1);
    expect(body.wraps[0].user_id).toBe("user-abc");
    expect(typeof body.title_ciphertext_b64).toBe("string");
    expect(typeof body.blob_ciphertext_b64).toBe("string");
    expect(typeof body.wraps[0].wrapped_key_b64).toBe("string");

    // Round-trip: unwrap secretKey vaultKey'ом, decrypt blob — должно
    // получиться обратно plaintext.
    const wrappedKey = fromBase64(body.wraps[0].wrapped_key_b64);
    const secretKey = await unwrapSecretKeyForUser(vaultKey, wrappedKey);
    const titlePlain = await decryptBlob(
      secretKey,
      fromBase64(body.title_ciphertext_b64),
    );
    expect(titlePlain).toBe("Production DB");
    const blobPlain = await decryptBlob(
      secretKey,
      fromBase64(body.blob_ciphertext_b64),
    );
    expect(blobPlain).toBe("postgres://user:pass@host");

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  it("backend 422 → отображает status + не вызывает onSuccess", async () => {
    const vaultKey = await makeVaultKey();
    setVaultKey(vaultKey);

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "bad category" }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const onSuccess = vi.fn();
    render(
      <CreateSecretForm
        userId="user-1"
        onCancel={vi.fn()}
        onSuccess={onSuccess}
      />,
    );
    fireEvent.change(screen.getByLabelText(/Title/), {
      target: { value: "X" },
    });
    fireEvent.change(screen.getByLabelText(/Содержимое/), {
      target: { value: "X" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/422/);
    });
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("Отмена вызывает onCancel", () => {
    const onCancel = vi.fn();
    render(
      <CreateSecretForm
        userId="user-1"
        onCancel={onCancel}
        onSuccess={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onCancel).toHaveBeenCalled();
  });
});
