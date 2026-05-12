import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import NewSessionButton from "./new-session-button";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  pushMock.mockReset();
  window.localStorage.clear();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

describe("NewSessionButton", () => {
  it("create new session → save token + push", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "sess-1",
          user_id: null,
          scope: "guest",
          context: {},
          created_at: "2026-05-12T00:00:00Z",
          expires_at: "2026-05-13T00:00:00Z",
        }),
        {
          status: 201,
          headers: { "X-Chat-Session-Token": "tok-abc" },
        },
      ),
    );
    render(<NewSessionButton />);
    fireEvent.click(screen.getByText(/Новая сессия/));
    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/chat/sess-1");
    });
    // Token saved
    const raw = window.localStorage.getItem("rehome_chat_session_tokens");
    expect(raw).toContain("tok-abc");
  });

  it("shows error on 5xx", async () => {
    fetchMock.mockResolvedValueOnce(new Response("err", { status: 500 }));
    render(<NewSessionButton />);
    fireEvent.click(screen.getByText(/Новая сессия/));
    await waitFor(() => {
      expect(
        screen.getByText(/Не удалось создать сессию|API error/),
      ).toBeInTheDocument();
    });
  });
});
