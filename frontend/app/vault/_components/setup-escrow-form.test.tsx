import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SetupEscrowForm from "./setup-escrow-form";

const fetchMock = vi.fn();

beforeEach(() => {
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
});

afterEach(() => {
  cleanup();
});

// Salt is deterministic-but-arbitrary; ceremony doesn't validate semantics.
const SALT_B64 = "AAAAAAAAAAAAAAAAAAAAAA=="; // 16 zero bytes

function _setupSuccessResp() {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    text: async () => JSON.stringify({ has_escrow: true }),
  });
}

describe("SetupEscrowForm", () => {
  it("показывает password prompt + warning перед ceremony", () => {
    render(
      <SetupEscrowForm argonSaltB64={SALT_B64} onSuccess={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByText(/Настроить emergency access/)).toBeDefined();
    expect(screen.getByText(/shares показываются ТОЛЬКО ОДИН раз/i)).toBeDefined();
    expect(screen.getByText(/Master password/)).toBeDefined();
  });

  it("cancel button calls onCancel", () => {
    const onCancel = vi.fn();
    render(
      <SetupEscrowForm
        argonSaltB64={SALT_B64}
        onSuccess={vi.fn()}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("happy path: enter password → generates shares → confirm acks → success", async () => {
    _setupSuccessResp();
    const onSuccess = vi.fn();
    render(
      <SetupEscrowForm
        argonSaltB64={SALT_B64}
        onSuccess={onSuccess}
        onCancel={vi.fn()}
      />,
    );

    // Step 1: enter password.
    fireEvent.change(screen.getByLabelText(/Master password/), {
      target: { value: "correct horse battery staple" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Сгенерировать shares/ }));

    // Wait for shares display (Argon2id derivation may take a moment).
    await waitFor(
      () => {
        expect(screen.getByText(/Распечатайте shares/)).toBeDefined();
      },
      { timeout: 10000 },
    );

    // Both shares shown.
    const directorShare = screen.getByTestId("share-director");
    const lawyerShare = screen.getByTestId("share-lawyer");
    expect(directorShare.textContent).toMatch(/^[A-Z2-7 ]+$/);
    expect(lawyerShare.textContent).toMatch(/^[A-Z2-7 ]+$/);
    expect(directorShare.textContent).not.toBe(lawyerShare.textContent);

    // Confirm both envelopes ack'ed.
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    fireEvent.click(screen.getByRole("button", { name: "Завершить ceremony" }));
    expect(onSuccess).toHaveBeenCalledOnce();
  }, 15000);

  it("POST /vault/setup-escrow с правильным payload shape", async () => {
    _setupSuccessResp();
    render(
      <SetupEscrowForm argonSaltB64={SALT_B64} onSuccess={vi.fn()} onCancel={vi.fn()} />,
    );
    fireEvent.change(screen.getByLabelText(/Master password/), {
      target: { value: "test-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Сгенерировать shares/ }));
    await waitFor(
      () => {
        expect(screen.getByText(/Распечатайте shares/)).toBeDefined();
      },
      { timeout: 10000 },
    );
    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("/api/v1/vault/setup-escrow");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(typeof body.escrow_wrap_b64).toBe("string");
    expect(body.escrow_wrap_b64.length).toBeGreaterThan(0);
  }, 15000);

  it("backend 500 → error displayed, остаётся на step=password", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ detail: "boom" }),
      text: async () => JSON.stringify({ detail: "boom" }),
    });
    render(
      <SetupEscrowForm argonSaltB64={SALT_B64} onSuccess={vi.fn()} onCancel={vi.fn()} />,
    );
    fireEvent.change(screen.getByLabelText(/Master password/), {
      target: { value: "test-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Сгенерировать shares/ }));
    await waitFor(
      () => {
        expect(screen.getByRole("alert").textContent).toMatch(/500/);
      },
      { timeout: 10000 },
    );
    // Should still be on password step.
    expect(screen.getByText(/Master password/)).toBeDefined();
  }, 15000);

  it("завершить ceremony disabled пока оба ack'а не отмечены", async () => {
    _setupSuccessResp();
    render(
      <SetupEscrowForm argonSaltB64={SALT_B64} onSuccess={vi.fn()} onCancel={vi.fn()} />,
    );
    fireEvent.change(screen.getByLabelText(/Master password/), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Сгенерировать shares/ }));
    await waitFor(
      () => {
        expect(screen.getByText(/Распечатайте shares/)).toBeDefined();
      },
      { timeout: 10000 },
    );

    const finishBtn = screen.getByRole("button", { name: "Завершить ceremony" });
    expect((finishBtn as HTMLButtonElement).disabled).toBe(true);

    // Tick only first checkbox.
    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    expect((finishBtn as HTMLButtonElement).disabled).toBe(true);

    // Both ticked → enabled.
    fireEvent.click(checkboxes[1]);
    expect((finishBtn as HTMLButtonElement).disabled).toBe(false);
  }, 15000);
});
