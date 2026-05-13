import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import WebhooksTable from "./webhooks-table";
import type { Webhook } from "@/lib/api/types";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

const fetchMock = vi.fn();
const confirmMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

function _make(id: string, overrides: Partial<Webhook> = {}): Webhook {
  return {
    id,
    client_id: "alice",
    url: "https://example.com/h",
    events: ["article.published"],
    secret: "shh",
    description: null,
    created_at: "2026-05-13T00:00:00Z",
    last_delivery_at: null,
    last_delivery_status: null,
    ...overrides,
  };
}

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  refreshMock.mockReset();
  confirmMock.mockReset();
  window.confirm = confirmMock as typeof window.confirm;
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

describe("WebhooksTable", () => {
  it("renders empty state when no webhooks", () => {
    render(<WebhooksTable webhooks={[]} />);
    expect(screen.getByText(/Нет активных подписок/)).toBeInTheDocument();
  });

  it("renders rows with URL + events", () => {
    render(
      <WebhooksTable
        webhooks={[
          _make("w1"),
          _make("w2", { url: "https://other.example/h", events: ["chat.escalated"] }),
        ]}
      />,
    );
    expect(screen.getAllByRole("row").length).toBe(3); // header + 2 rows
    expect(screen.getByText("chat.escalated")).toBeInTheDocument();
  });

  it("Test button POSTs and shows delivery_id", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ delivery_id: "deadbeef-uuid", status: "enqueued" }),
        { status: 202 },
      ),
    );
    render(<WebhooksTable webhooks={[_make("w1")]} />);
    fireEvent.click(screen.getByText("Test"));
    await waitFor(() => {
      expect(screen.getByText(/Test delivery enqueued/)).toBeInTheDocument();
    });
  });

  it("Delete cancelled by window.confirm → no fetch", () => {
    confirmMock.mockReturnValueOnce(false);
    render(<WebhooksTable webhooks={[_make("w1")]} />);
    fireEvent.click(screen.getByText("Удалить"));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("Delete confirmed → DELETE + router.refresh()", async () => {
    confirmMock.mockReturnValueOnce(true);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(<WebhooksTable webhooks={[_make("w1")]} />);
    fireEvent.click(screen.getByText("Удалить"));
    await waitFor(() => {
      expect(refreshMock).toHaveBeenCalledOnce();
    });
  });
});
