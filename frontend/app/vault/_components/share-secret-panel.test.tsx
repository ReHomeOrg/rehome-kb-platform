import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { generateSecretKey } from "@/lib/vault/crypto";

import ShareSecretPanel from "./share-secret-panel";

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const groupFixture = {
  id: "g-1",
  name: "backend-team",
  description: null,
  created_by: "owner-1",
  created_at: "2026-05-17T00:00:00Z",
};

function memberFixture(userId: string): unknown {
  return {
    group_id: "g-1",
    user_id: userId,
    role: "member",
    added_at: "2026-05-17T00:00:00Z",
  };
}

describe("ShareSecretPanel", () => {
  it("показывает empty state когда групп нет", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));
    const secretKey = await generateSecretKey();
    render(
      <ShareSecretPanel
        secretId="s-1"
        ownerId="owner-1"
        secretKey={secretKey}
        onCancel={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByText(/Вы не состоите ни в одной группе/),
      ).toBeInTheDocument();
    });
  });

  it("кнопка Поделиться disabled пока не выбрана группа", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [groupFixture] }));
    const secretKey = await generateSecretKey();
    render(
      <ShareSecretPanel
        secretId="s-1"
        ownerId="owner-1"
        secretKey={secretKey}
        onCancel={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("backend-team")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Поделиться" })).toBeDisabled();
  });

  it("error если в группе нет других участников", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ data: [groupFixture] }))
      // list members — только owner
      .mockResolvedValueOnce(
        jsonResponse({ data: [memberFixture("owner-1")] }),
      );
    const secretKey = await generateSecretKey();
    render(
      <ShareSecretPanel
        secretId="s-1"
        ownerId="owner-1"
        secretKey={secretKey}
        onCancel={vi.fn()}
        onSuccess={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("backend-team")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText(/Группа/), {
      target: { value: "g-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Поделиться" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /некому шарить/,
      );
    });
  });

  it("happy path — bulk pubkey lookup + POSTs wraps с group_id lineage", async () => {
    // Real X25519 pubkey (32 bytes) — generate via WebCrypto helper.
    const { generateX25519Keypair, toBase64 } = await import(
      "@/lib/vault/crypto"
    );
    const recipientKp = generateX25519Keypair();

    fetchMock
      .mockResolvedValueOnce(jsonResponse({ data: [groupFixture] }))
      // listGroupMembers
      .mockResolvedValueOnce(
        jsonResponse({
          data: [
            memberFixture("owner-1"),
            memberFixture("user-2"),
          ],
        }),
      )
      // bulk pubkeys (POST /users/pubkeys)
      .mockResolvedValueOnce(
        jsonResponse({
          data: [
            {
              user_id: "user-2",
              x25519_pubkey_b64: toBase64(recipientKp.pubkey),
            },
          ],
        }),
      )
      // addSecretWraps
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    const onSuccess = vi.fn();
    const secretKey = await generateSecretKey();
    render(
      <ShareSecretPanel
        secretId="s-1"
        ownerId="owner-1"
        secretKey={secretKey}
        onCancel={vi.fn()}
        onSuccess={onSuccess}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("backend-team")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText(/Группа/), {
      target: { value: "g-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Поделиться" }));

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled();
    });

    // Bulk pubkey call — POST /users/pubkeys c одним user_id в теле.
    const pubkeysCall = fetchMock.mock.calls[2]!;
    expect(pubkeysCall[0]).toBe("/api/kb/api/v1/vault/users/pubkeys");
    const pubkeysBody = JSON.parse(
      (pubkeysCall[1] as RequestInit).body as string,
    );
    expect(pubkeysBody.user_ids).toEqual(["user-2"]);

    // Assert wraps body имеет group_id lineage и user_id ректа.
    const wrapsCall = fetchMock.mock.calls[3]!;
    expect(wrapsCall[0]).toBe("/api/kb/api/v1/vault/secrets/s-1/wraps");
    const body = JSON.parse((wrapsCall[1] as RequestInit).body as string);
    expect(body.wraps).toHaveLength(1);
    expect(body.wraps[0].user_id).toBe("user-2");
    expect(body.wraps[0].group_id).toBe("g-1");
    expect(body.wraps[0].wrapped_key_b64).toBeTruthy();
  });

  it("partial missing pubkey — saves для sharable, оставляет warning", async () => {
    const { generateX25519Keypair, toBase64 } = await import(
      "@/lib/vault/crypto"
    );
    const recipientKp = generateX25519Keypair();

    fetchMock
      .mockResolvedValueOnce(jsonResponse({ data: [groupFixture] }))
      .mockResolvedValueOnce(
        jsonResponse({
          data: [
            memberFixture("owner-1"),
            memberFixture("user-2"),
            memberFixture("user-3-no-vault"),
          ],
        }),
      )
      // bulk pubkeys — user-3-no-vault не setup'нул vault, отсутствует в data
      .mockResolvedValueOnce(
        jsonResponse({
          data: [
            {
              user_id: "user-2",
              x25519_pubkey_b64: toBase64(recipientKp.pubkey),
            },
          ],
        }),
      )
      // addSecretWraps — успешно для user-2
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    const onSuccess = vi.fn();
    const secretKey = await generateSecretKey();
    render(
      <ShareSecretPanel
        secretId="s-1"
        ownerId="owner-1"
        secretKey={secretKey}
        onCancel={vi.fn()}
        onSuccess={onSuccess}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("backend-team")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText(/Группа/), {
      target: { value: "g-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Поделиться" }));

    // Wraps сохранены для user-2.
    await waitFor(() => {
      const wrapsCall = fetchMock.mock.calls[3];
      expect(wrapsCall?.[0]).toBe("/api/kb/api/v1/vault/secrets/s-1/wraps");
    });
    // Warning видим, onSuccess не вызвана (panel остаётся открытой).
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/пропущены/);
    });
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("all missing pubkey — error без POST wraps", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ data: [groupFixture] }))
      .mockResolvedValueOnce(
        jsonResponse({
          data: [
            memberFixture("owner-1"),
            memberFixture("user-no-vault"),
          ],
        }),
      )
      // bulk pubkeys — empty (никто не setup'нул vault)
      .mockResolvedValueOnce(jsonResponse({ data: [] }));

    const onSuccess = vi.fn();
    const secretKey = await generateSecretKey();
    render(
      <ShareSecretPanel
        secretId="s-1"
        ownerId="owner-1"
        secretKey={secretKey}
        onCancel={vi.fn()}
        onSuccess={onSuccess}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("backend-team")).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText(/Группа/), {
      target: { value: "g-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Поделиться" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/нечего шарить/);
    });
    // Нет 4-го fetch'а (wraps POST не делался).
    expect(fetchMock.mock.calls.length).toBe(3);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("Закрыть вызывает onCancel", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));
    const onCancel = vi.fn();
    const secretKey = await generateSecretKey();
    render(
      <ShareSecretPanel
        secretId="s-1"
        ownerId="owner-1"
        secretKey={secretKey}
        onCancel={onCancel}
        onSuccess={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/Вы не состоите/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(onCancel).toHaveBeenCalled();
  });
});
