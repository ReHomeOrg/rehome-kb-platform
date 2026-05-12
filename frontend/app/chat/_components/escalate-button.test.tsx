import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import EscalateButton from "./escalate-button";

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

describe("EscalateButton", () => {
  it("renders initial button", () => {
    render(<EscalateButton sessionId="s" sessionToken="t" />);
    expect(screen.getByText(/Эскалировать/)).toBeInTheDocument();
  });

  it("submit → shows ticket on success", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ticket_id: "abcdef1234567890",
          estimated_response_time_minutes: 30,
        }),
        { status: 201 },
      ),
    );
    render(<EscalateButton sessionId="s" sessionToken="t" />);
    fireEvent.click(screen.getByText(/Эскалировать/));
    await waitFor(() => {
      expect(screen.getByText(/Тикет создан/)).toBeInTheDocument();
      expect(screen.getByText(/30 мин/)).toBeInTheDocument();
    });
  });

  it("shows error on 5xx", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("err", { status: 500 }),
    );
    render(<EscalateButton sessionId="s" sessionToken="t" />);
    fireEvent.click(screen.getByText(/Эскалировать/));
    await waitFor(() => {
      expect(screen.getByText(/Не удалось эскалировать/)).toBeInTheDocument();
    });
  });
});
