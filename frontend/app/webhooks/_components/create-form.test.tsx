import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CreateForm from "./create-form";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  refreshMock.mockReset();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

describe("CreateForm", () => {
  it("renders URL input + event checkboxes", () => {
    render(<CreateForm />);
    expect(
      screen.getByPlaceholderText(/https:\/\/your-app/),
    ).toBeInTheDocument();
    expect(screen.getByText("article.published")).toBeInTheDocument();
    expect(screen.getByText("chat.escalated")).toBeInTheDocument();
  });

  it("blocks submit when no events are selected", async () => {
    render(<CreateForm />);
    fireEvent.change(screen.getByPlaceholderText(/https:\/\/your-app/), {
      target: { value: "https://example.com/h" },
    });
    fireEvent.click(screen.getByText("Создать webhook"));
    await waitFor(() => {
      expect(
        screen.getByText(/Выберите хотя бы одно событие/),
      ).toBeInTheDocument();
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("on success shows secret banner + calls router.refresh()", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "wh-id",
          client_id: "alice",
          url: "https://example.com/h",
          events: ["article.published"],
          secret: "super-secret-token",
          description: null,
          created_at: "2026-05-13T00:00:00Z",
          last_delivery_at: null,
          last_delivery_status: null,
        }),
        { status: 201 },
      ),
    );
    render(<CreateForm />);
    fireEvent.change(screen.getByPlaceholderText(/https:\/\/your-app/), {
      target: { value: "https://example.com/h" },
    });
    fireEvent.click(screen.getByLabelText(/article.published/));
    fireEvent.click(screen.getByText("Создать webhook"));
    await waitFor(() => {
      expect(screen.getByText("super-secret-token")).toBeInTheDocument();
      expect(refreshMock).toHaveBeenCalledOnce();
    });
  });

  it("secret banner dismisses on click", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "wh-id",
          client_id: "alice",
          url: "https://example.com/h",
          events: ["article.published"],
          secret: "shh-keep-me",
          description: null,
          created_at: "2026-05-13T00:00:00Z",
          last_delivery_at: null,
          last_delivery_status: null,
        }),
        { status: 201 },
      ),
    );
    render(<CreateForm />);
    fireEvent.change(screen.getByPlaceholderText(/https:\/\/your-app/), {
      target: { value: "https://example.com/h" },
    });
    fireEvent.click(screen.getByLabelText(/article.published/));
    fireEvent.click(screen.getByText("Создать webhook"));
    await waitFor(() => {
      expect(screen.getByText("shh-keep-me")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("Я сохранил secret"));
    await waitFor(() => {
      expect(screen.queryByText("shh-keep-me")).not.toBeInTheDocument();
    });
  });

  it("shows API error detail on 400", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "URL resolves to private IP" }),
        { status: 400 },
      ),
    );
    render(<CreateForm />);
    fireEvent.change(screen.getByPlaceholderText(/https:\/\/your-app/), {
      target: { value: "http://localhost/h" },
    });
    fireEvent.click(screen.getByLabelText(/article.published/));
    fireEvent.click(screen.getByText("Создать webhook"));
    await waitFor(() => {
      expect(
        screen.getByText(/URL resolves to private IP/),
      ).toBeInTheDocument();
    });
  });
});
