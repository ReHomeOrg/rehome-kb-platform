import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { randomBytes, toBase64 } from "@/lib/vault/crypto";
import { shareToBase32, splitSecret } from "@/lib/vault/escrow";

import EmergencyUnlockForm from "./emergency-unlock-form";

const fetchMock = vi.fn();

beforeEach(() => {
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
});

afterEach(() => {
  cleanup();
});

const VALID_UUID = "12345678-1234-1234-1234-1234567890ab";
const VALID_REASON =
  "Suspected breach reported via security@; ticket SEC-2026-05-21-001";

/**
 * Build a fake encrypted payload that matches the real ceremony shape:
 * - generate random escrow_key
 * - AES-GCM encrypt random KEK under escrow_key → escrow_wrap
 * - AES-GCM encrypt random privkey under KEK → encrypted_x25519_privkey
 * Returns split shares + payload в JSON shape backend returns.
 */
async function _buildCeremonyFixture() {
  const escrowKey = randomBytes(32);
  const kek = randomBytes(32);
  const privkey = randomBytes(32);
  const pubkey = randomBytes(32);
  const argonSalt = randomBytes(16);

  async function gcmEncrypt(plain: Uint8Array, keyBytes: Uint8Array): Promise<Uint8Array> {
    const iv = randomBytes(12);
    const key = await crypto.subtle.importKey(
      "raw",
      keyBytes as BufferSource,
      { name: "AES-GCM", length: 256 },
      false,
      ["encrypt"],
    );
    const ct = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: iv as BufferSource },
      key,
      plain as BufferSource,
    );
    const blob = new Uint8Array(iv.length + ct.byteLength);
    blob.set(iv, 0);
    blob.set(new Uint8Array(ct), iv.length);
    return blob;
  }

  const escrowWrap = await gcmEncrypt(kek, escrowKey);
  const encPriv = await gcmEncrypt(privkey, kek);
  const shares = await splitSecret(escrowKey, { threshold: 2 });

  return {
    expectedKekHex: Array.from(kek)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join(""),
    expectedPrivkeyHex: Array.from(privkey)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join(""),
    share1Base32: shareToBase32(shares[0]),
    share2Base32: shareToBase32(shares[1]),
    backendResp: {
      unlock_log_id: "00000000-0000-0000-0000-000000000001",
      security_incident_id: "00000000-0000-0000-0000-000000000002",
      rkn_notify_required: false,
      severity: "low",
      created_at: "2026-05-21T12:00:00Z",
      vault: {
        escrow_wrap_b64: toBase64(escrowWrap),
        encrypted_x25519_privkey_b64: toBase64(encPriv),
        x25519_pubkey_b64: toBase64(pubkey),
        argon_salt_b64: toBase64(argonSalt),
      },
    },
  };
}

describe("EmergencyUnlockForm", () => {
  it("submit disabled пока share1/share2 пустые или reason_text < 10", () => {
    render(<EmergencyUnlockForm />);
    const submit = screen.getByRole("button", {
      name: /Combine shares/,
    }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it("happy path: combine shares + decrypt + display recovered material", async () => {
    const fx = await _buildCeremonyFixture();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(fx.backendResp),
    });

    render(<EmergencyUnlockForm />);

    fireEvent.change(screen.getByLabelText(/Target user ID/), {
      target: { value: VALID_UUID },
    });
    fireEvent.change(screen.getByLabelText(/Reason details/), {
      target: { value: VALID_REASON },
    });
    fireEvent.change(screen.getByLabelText(/Share 1/), {
      target: { value: fx.share1Base32 },
    });
    fireEvent.change(screen.getByLabelText(/Share 2/), {
      target: { value: fx.share2Base32 },
    });

    fireEvent.click(screen.getByRole("button", { name: /Combine shares/ }));

    await waitFor(() => {
      expect(screen.getByText(/Vault recovery успешна/)).toBeDefined();
    });

    // Recovered material matches fixture.
    expect(screen.getByTestId("recovered-kek").textContent).toBe(fx.expectedKekHex);
    expect(screen.getByTestId("recovered-privkey").textContent).toBe(fx.expectedPrivkeyHex);

    // Audit metadata visible.
    expect(screen.getByText(fx.backendResp.unlock_log_id)).toBeDefined();
    expect(screen.getByText(fx.backendResp.security_incident_id)).toBeDefined();
  });

  it("POST body содержит правильный reason_category + reason_text", async () => {
    const fx = await _buildCeremonyFixture();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(fx.backendResp),
    });

    render(<EmergencyUnlockForm />);
    fireEvent.change(screen.getByLabelText(/Target user ID/), {
      target: { value: VALID_UUID },
    });
    fireEvent.change(screen.getByLabelText(/Reason category/), {
      target: { value: "incident" },
    });
    fireEvent.change(screen.getByLabelText(/Reason details/), {
      target: { value: VALID_REASON },
    });
    fireEvent.change(screen.getByLabelText(/Share 1/), {
      target: { value: fx.share1Base32 },
    });
    fireEvent.change(screen.getByLabelText(/Share 2/), {
      target: { value: fx.share2Base32 },
    });
    fireEvent.click(screen.getByRole("button", { name: /Combine shares/ }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.target_user_id).toBe(VALID_UUID);
    expect(body.reason_category).toBe("incident");
    expect(body.reason_text).toBe(VALID_REASON);
  });

  it("corrupted share → EscrowError displayed, no POST issued", async () => {
    render(<EmergencyUnlockForm />);
    fireEvent.change(screen.getByLabelText(/Target user ID/), {
      target: { value: VALID_UUID },
    });
    fireEvent.change(screen.getByLabelText(/Reason details/), {
      target: { value: VALID_REASON },
    });
    fireEvent.change(screen.getByLabelText(/Share 1/), {
      target: { value: "AAAAAAAAAA" },
    });
    fireEvent.change(screen.getByLabelText(/Share 2/), {
      target: { value: "BBBBBBBBBB" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Combine shares/ }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined();
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("backend 403 → friendly error retained", async () => {
    const fx = await _buildCeremonyFixture();
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Требуется staff_admin scope" }),
      text: async () => JSON.stringify({ detail: "Требуется staff_admin scope" }),
    });
    render(<EmergencyUnlockForm />);
    fireEvent.change(screen.getByLabelText(/Target user ID/), {
      target: { value: VALID_UUID },
    });
    fireEvent.change(screen.getByLabelText(/Reason details/), {
      target: { value: VALID_REASON },
    });
    fireEvent.change(screen.getByLabelText(/Share 1/), {
      target: { value: fx.share1Base32 },
    });
    fireEvent.change(screen.getByLabelText(/Share 2/), {
      target: { value: fx.share2Base32 },
    });
    fireEvent.click(screen.getByRole("button", { name: /Combine shares/ }));

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toMatch(/403/);
    });
  });

  it("clear button drops recovered state", async () => {
    const fx = await _buildCeremonyFixture();
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => JSON.stringify(fx.backendResp),
    });
    render(<EmergencyUnlockForm />);
    fireEvent.change(screen.getByLabelText(/Target user ID/), {
      target: { value: VALID_UUID },
    });
    fireEvent.change(screen.getByLabelText(/Reason details/), {
      target: { value: VALID_REASON },
    });
    fireEvent.change(screen.getByLabelText(/Share 1/), {
      target: { value: fx.share1Base32 },
    });
    fireEvent.change(screen.getByLabelText(/Share 2/), {
      target: { value: fx.share2Base32 },
    });
    fireEvent.click(screen.getByRole("button", { name: /Combine shares/ }));
    await waitFor(() => {
      expect(screen.getByText(/Vault recovery успешна/)).toBeDefined();
    });
    fireEvent.click(screen.getByRole("button", { name: /Очистить/ }));
    expect(screen.queryByText(/Vault recovery успешна/)).toBeNull();
    expect(screen.queryByTestId("recovered-kek")).toBeNull();
    // Form back to initial state.
    expect(screen.getByRole("button", { name: /Combine shares/ })).toBeDefined();
  });
});
