import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FeedbackButtons from "./feedback-buttons";

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window; // jsdom keeps window
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

describe("FeedbackButtons", () => {
  it("renders both buttons", () => {
    render(
      <FeedbackButtons
        sessionId="s"
        messageId="m"
        sessionToken="t"
        initial={null}
      />,
    );
    expect(screen.getByLabelText("Полезный ответ")).toBeInTheDocument();
    expect(screen.getByLabelText("Неполезный ответ")).toBeInTheDocument();
  });

  it("highlights initial up", () => {
    render(
      <FeedbackButtons
        sessionId="s"
        messageId="m"
        sessionToken="t"
        initial="up"
      />,
    );
    expect(screen.getByLabelText("Полезный ответ").className).toContain(
      "bg-green-100",
    );
  });

  it("click up → fetch POST /feedback → highlight", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 201 }));
    render(
      <FeedbackButtons
        sessionId="s1"
        messageId="m1"
        sessionToken="tok"
        initial={null}
      />,
    );
    fireEvent.click(screen.getByLabelText("Полезный ответ"));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
      const [, init] = fetchMock.mock.calls[0];
      const body = JSON.parse((init as RequestInit).body as string);
      expect(body.rating).toBe("up");
    });
  });
});
