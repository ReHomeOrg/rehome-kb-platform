import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { addRecentSession } from "@/lib/chat-storage";

import SessionList from "./session-list";

beforeEach(() => {
  window.localStorage.clear();
});

describe("SessionList", () => {
  it("empty state when no recent sessions", async () => {
    render(<SessionList />);
    await waitFor(() => {
      expect(screen.getByText(/Недавних сессий нет/)).toBeInTheDocument();
    });
  });

  it("renders sessions from localStorage", async () => {
    addRecentSession({
      id: "11111111-2222-3333-4444-555555555555",
      created_at: "2026-05-12T00:00:00Z",
      scope: "guest",
    });
    render(<SessionList />);
    await waitFor(() => {
      expect(screen.getByText(/11111111/)).toBeInTheDocument();
      expect(screen.getByText(/guest/)).toBeInTheDocument();
    });
  });

  it("links to /chat/[id]", async () => {
    addRecentSession({
      id: "abcdef12-3456-7890-abcd-ef1234567890",
      created_at: "2026-05-12T00:00:00Z",
      scope: "tenant",
    });
    render(<SessionList />);
    await waitFor(() => {
      const link = screen.getByText(/abcdef12/).closest("a");
      expect(link?.getAttribute("href")).toBe(
        "/chat/abcdef12-3456-7890-abcd-ef1234567890",
      );
    });
  });
});
