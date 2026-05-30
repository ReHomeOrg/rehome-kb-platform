import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { generateX25519Keypair, toBase64 } from "@/lib/vault/crypto";
import { lock, setVaultKey } from "@/lib/vault/session";

import RecipientsPanel from "./recipients-panel";

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

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

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function emptyResponse(status = 204): Response {
  return new Response(null, { status });
}

describe("RecipientsPanel", () => {
  it("показывает empty state когда список wraps пустой", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));
    render(
      <RecipientsPanel
        secretId="s-1"
        ownerId="owner-1"
        plaintextTitle="title"
        plaintextPayload="payload"
        currentVersion={1}
        onCancel={vi.fn()}
        onRotated={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByText(/Никому не расшарено/),
      ).toBeInTheDocument();
    });
  });

  it("показывает recipients + revoke кнопки (НЕ для owner)", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [
          { user_id: "owner-1", group_id: null },
          { user_id: "user-2", group_id: null },
          { user_id: "user-3", group_id: "g-x" },
        ],
      }),
    );
    render(
      <RecipientsPanel
        secretId="s-1"
        ownerId="owner-1"
        plaintextTitle="title"
        plaintextPayload="payload"
        currentVersion={1}
        onCancel={vi.fn()}
        onRotated={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("owner-1")).toBeInTheDocument();
    });
    expect(screen.getByText("user-2")).toBeInTheDocument();
    expect(screen.getByText("user-3")).toBeInTheDocument();
    // Owner row — no revoke button, special label.
    expect(screen.getByText("(вы — owner)")).toBeInTheDocument();
    // 2 revoke buttons (для user-2 + user-3).
    expect(screen.getAllByRole("button", { name: "Отозвать" }).length).toBe(2);
  });

  it("блокирует revoke если vault locked", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [
          { user_id: "owner-1", group_id: null },
          { user_id: "user-2", group_id: null },
        ],
      }),
    );
    lock(); // ensure locked
    render(
      <RecipientsPanel
        secretId="s-1"
        ownerId="owner-1"
        plaintextTitle="title"
        plaintextPayload="payload"
        currentVersion={1}
        onCancel={vi.fn()}
        onRotated={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Отозвать" })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "Отозвать" }));
    await waitFor(() => {
      expect(screen.getByText(/Vault locked/)).toBeInTheDocument();
    });
    // rotate endpoint НЕ должен быть вызван — только GET /wraps был.
    expect(fetchMock.mock.calls.length).toBe(1);
  });

  it("revoke flow: rotation вызывает /rotate с new_title, new_blob, expected_version, new_wraps", async () => {
    // Setup vault key (with wrapKey/unwrapKey usages для self-wrap).
    const vaultKey = await crypto.subtle.generateKey(
      { name: "AES-GCM", length: 256 },
      false,
      ["wrapKey", "unwrapKey"],
    );
    setVaultKey(vaultKey);

    // GET /wraps — owner + user-2.
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [
          { user_id: "owner-1", group_id: null },
          { user_id: "user-2", group_id: null },
        ],
      }),
    );
    // GET /users/owner-1/pubkey — НЕ запрашивается (owner-self-wrap через vaultKey).
    // GET /users/user-2/pubkey — pubkey survivor'а user-2... но если revoke user-2,
    // он survivor НЕ является. Для revoke owner есть только сам owner — single wrap.
    // На самом деле в этом сценарии: revoke user-2 → survivors = [owner-1] → 0 external lookups.
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: "s-1",
        owner_id: "owner-1",
        title_ciphertext_b64: toBase64(new Uint8Array([1, 2, 3])),
        category: "x",
        created_at: "2026-05-27T00:00:00Z",
        updated_at: "2026-05-27T00:00:00Z",
        expires_at: null,
        archived_at: null,
        blob_ciphertext_b64: toBase64(new Uint8Array([4, 5, 6])),
        payload_version: 2,
        wrapped_key_b64: toBase64(new Uint8Array(64)),
        via_group_id: null,
      }),
    );

    const onRotated = vi.fn();
    render(
      <RecipientsPanel
        secretId="s-1"
        ownerId="owner-1"
        plaintextTitle="title-plain"
        plaintextPayload="payload-plain"
        currentVersion={1}
        onCancel={vi.fn()}
        onRotated={onRotated}
      />,
    );
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Отозвать" })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "Отозвать" }));

    await waitFor(() => {
      expect(onRotated).toHaveBeenCalledTimes(1);
    });

    // Verify the POST /rotate request shape.
    const rotateCall = fetchMock.mock.calls.find(
      ([url]) => typeof url === "string" && url.includes("/rotate"),
    );
    expect(rotateCall).toBeDefined();
    const [, init] = rotateCall as [string, RequestInit];
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string) as {
      new_title_ciphertext_b64: string;
      new_blob_ciphertext_b64: string;
      expected_version: number;
      new_wraps: { user_id: string }[];
    };
    expect(body.expected_version).toBe(1);
    expect(typeof body.new_title_ciphertext_b64).toBe("string");
    expect(body.new_title_ciphertext_b64.length).toBeGreaterThan(0);
    expect(typeof body.new_blob_ciphertext_b64).toBe("string");
    expect(body.new_blob_ciphertext_b64.length).toBeGreaterThan(0);
    // Survivors = только owner (user-2 revoked).
    expect(body.new_wraps).toHaveLength(1);
    expect(body.new_wraps[0]?.user_id).toBe("owner-1");
  });

  it("revoke с external survivor: fetch pubkey + wrap включается", async () => {
    const vaultKey = await crypto.subtle.generateKey(
      { name: "AES-GCM", length: 256 },
      false,
      ["wrapKey", "unwrapKey"],
    );
    setVaultKey(vaultKey);
    const survivorKeypair = generateX25519Keypair();

    // GET /wraps — owner + user-2 + user-3.
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [
          { user_id: "owner-1", group_id: null },
          { user_id: "user-2", group_id: null },
          { user_id: "user-3", group_id: null },
        ],
      }),
    );
    // POST /users/pubkeys — bulk lookup (survivor user-3; user-2 будет revoked).
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [
          {
            user_id: "user-3",
            x25519_pubkey_b64: toBase64(survivorKeypair.pubkey),
          },
        ],
      }),
    );
    // POST /rotate response.
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        id: "s-1",
        owner_id: "owner-1",
        title_ciphertext_b64: toBase64(new Uint8Array([1])),
        category: "x",
        created_at: "2026-05-27T00:00:00Z",
        updated_at: "2026-05-27T00:00:00Z",
        expires_at: null,
        archived_at: null,
        blob_ciphertext_b64: toBase64(new Uint8Array([2])),
        payload_version: 2,
        wrapped_key_b64: toBase64(new Uint8Array(64)),
        via_group_id: null,
      }),
    );

    render(
      <RecipientsPanel
        secretId="s-1"
        ownerId="owner-1"
        plaintextTitle="title"
        plaintextPayload="payload"
        currentVersion={1}
        onCancel={vi.fn()}
        onRotated={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Отозвать" }).length).toBe(2);
    });
    // Кликаем «Отозвать» у первой кнопки (user-2).
    fireEvent.click(screen.getAllByRole("button", { name: "Отозвать" })[0]!);

    await waitFor(() => {
      const rotateCall = fetchMock.mock.calls.find(
        ([url]) => typeof url === "string" && url.includes("/rotate"),
      );
      expect(rotateCall).toBeDefined();
    });

    // Verify: bulk pubkey POST содержит user-3 в user_ids.
    const pubkeyCall = fetchMock.mock.calls.find(
      ([url]) =>
        typeof url === "string" && url.endsWith("/vault/users/pubkeys"),
    );
    expect(pubkeyCall).toBeDefined();
    const pubkeyBody = JSON.parse(
      (pubkeyCall![1] as RequestInit).body as string,
    );
    expect(pubkeyBody.user_ids).toEqual(["user-3"]);
    // Verify: rotate body содержит 2 wraps (owner + user-3).
    const rotateCall = fetchMock.mock.calls.find(
      ([url]) => typeof url === "string" && url.includes("/rotate"),
    );
    const body = JSON.parse((rotateCall![1] as RequestInit).body as string) as {
      new_wraps: { user_id: string }[];
    };
    const userIds = body.new_wraps.map((w) => w.user_id).sort();
    expect(userIds).toEqual(["owner-1", "user-3"]);
  });

  it("rotation fails если survivor не настроил vault — atomic invariant", async () => {
    const vaultKey = await crypto.subtle.generateKey(
      { name: "AES-GCM", length: 256 },
      false,
      ["wrapKey", "unwrapKey"],
    );
    setVaultKey(vaultKey);

    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [
          { user_id: "owner-1", group_id: null },
          { user_id: "user-2", group_id: null },
          { user_id: "user-3-no-vault", group_id: null },
        ],
      }),
    );
    // bulk pubkey — user-3-no-vault отсутствует.
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));

    const onRotated = vi.fn();
    render(
      <RecipientsPanel
        secretId="s-1"
        ownerId="owner-1"
        plaintextTitle="title"
        plaintextPayload="payload"
        currentVersion={1}
        onCancel={vi.fn()}
        onRotated={onRotated}
      />,
    );
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Отозвать" }).length).toBe(2);
    });
    // Отзываем user-2 → survivor user-3-no-vault должен получить wrap, но нет pubkey.
    fireEvent.click(screen.getAllByRole("button", { name: "Отозвать" })[0]!);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/настроили vault/);
    });
    // /rotate POST не делался.
    expect(
      fetchMock.mock.calls.find(
        ([url]) => typeof url === "string" && url.includes("/rotate"),
      ),
    ).toBeUndefined();
    expect(onRotated).not.toHaveBeenCalled();
  });

  it("onCancel вызывает callback", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));
    const onCancel = vi.fn();
    render(
      <RecipientsPanel
        secretId="s-1"
        ownerId="owner-1"
        plaintextTitle="title"
        plaintextPayload="payload"
        currentVersion={1}
        onCancel={onCancel}
        onRotated={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("Закрыть")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("Закрыть"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});

// Suppress unused-import warning for emptyResponse (kept for future tests).
void emptyResponse;
