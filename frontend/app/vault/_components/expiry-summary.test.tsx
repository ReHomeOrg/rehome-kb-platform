import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ExpirySummary from "./expiry-summary";

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

const MS_PER_DAY = 24 * 60 * 60 * 1000;

function rowFixture(over: Record<string, unknown> = {}): unknown {
  return {
    id: "s-1",
    title_ciphertext_b64: "x",
    category: "password",
    owner_id: "u1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-05-17T00:00:00Z",
    expires_at: null,
    archived_at: null,
    ...over,
  };
}

describe("ExpirySummary", () => {
  it("renders nothing если нет expires_at у секретов", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [rowFixture()] }));
    const { container } = render(<ExpirySummary reloadToken={0} />);
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    // Banner не должен появляться.
    expect(container.querySelector("[data-testid='expiry-summary']")).toBeNull();
  });

  it("renders banner с count для expiring soon (within 30 days)", async () => {
    const futureSoon = new Date(Date.now() + 5 * MS_PER_DAY).toISOString();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [
          rowFixture({ id: "s-1", expires_at: futureSoon }),
          rowFixture({ id: "s-2", expires_at: futureSoon }),
        ],
      }),
    );
    render(<ExpirySummary reloadToken={0} />);
    await waitFor(() => {
      expect(screen.getByTestId("expiry-summary")).toBeInTheDocument();
    });
    expect(screen.getByText(/2 секрета истекают/)).toBeInTheDocument();
  });

  it("renders banner с expired count", async () => {
    const past = new Date(Date.now() - 5 * MS_PER_DAY).toISOString();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [rowFixture({ expires_at: past })],
      }),
    );
    render(<ExpirySummary reloadToken={0} />);
    await waitFor(() => {
      expect(screen.getByTestId("expiry-summary")).toBeInTheDocument();
    });
    expect(screen.getByText(/1 секрет уже истёк/)).toBeInTheDocument();
  });

  it("игнорирует архивированные секреты", async () => {
    const past = new Date(Date.now() - 5 * MS_PER_DAY).toISOString();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [
          rowFixture({
            expires_at: past,
            archived_at: "2026-05-17T00:00:00Z",
          }),
        ],
      }),
    );
    const { container } = render(<ExpirySummary reloadToken={0} />);
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    expect(container.querySelector("[data-testid='expiry-summary']")).toBeNull();
  });

  it("игнорирует expires_at за пределами 30-дневного окна", async () => {
    const farFuture = new Date(Date.now() + 90 * MS_PER_DAY).toISOString();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [rowFixture({ expires_at: farFuture })],
      }),
    );
    const { container } = render(<ExpirySummary reloadToken={0} />);
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    expect(container.querySelector("[data-testid='expiry-summary']")).toBeNull();
  });

  it("Russian pluralization: 1/2/5 секретов", async () => {
    const soon = new Date(Date.now() + 5 * MS_PER_DAY).toISOString();
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [
          rowFixture({ id: "s-1", expires_at: soon }),
          rowFixture({ id: "s-2", expires_at: soon }),
          rowFixture({ id: "s-3", expires_at: soon }),
          rowFixture({ id: "s-4", expires_at: soon }),
          rowFixture({ id: "s-5", expires_at: soon }),
        ],
      }),
    );
    render(<ExpirySummary reloadToken={0} />);
    await waitFor(() => {
      expect(screen.getByTestId("expiry-summary")).toBeInTheDocument();
    });
    // 5 секретов → genitive plural "секретов истекают".
    expect(screen.getByText(/5 секретов истекают/)).toBeInTheDocument();
  });

  it("fetch error → role=alert", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Server error" }, 500),
    );
    render(<ExpirySummary reloadToken={0} />);
    await waitFor(() => {
      expect(screen.getByTestId("expiry-error")).toHaveTextContent(/500/);
    });
  });
});
