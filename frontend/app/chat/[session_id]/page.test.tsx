import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ChatThreadPage from "./page";

// MessageThread тянет fetch/SSE — изолируем, нам важен только рендер страницы.
vi.mock("../_components/message-thread", () => ({
  default: ({ sessionId }: { sessionId: string }) => (
    <div data-testid="thread">thread:{sessionId}</div>
  ),
}));

vi.mock("@/lib/chat-storage", () => ({
  getSessionToken: () => "tok-xyz",
}));

describe("ChatThreadPage", () => {
  it("рендерит без исключения с обычным объектом params (Next 14, не Promise)", async () => {
    // Регресс на use(params): на Next 14 params — обычный объект; use() бросал бы
    // "An unsupported type was passed to use()" → error boundary.
    expect(() =>
      render(<ChatThreadPage params={{ session_id: "abcd1234-session" }} />),
    ).not.toThrow();

    expect(screen.getByText(/Сессия abcd1234/)).toBeInTheDocument();
    // После гидрации (useEffect) монтируется MessageThread с тем же sessionId.
    await waitFor(() =>
      expect(screen.getByTestId("thread")).toHaveTextContent(
        "thread:abcd1234-session",
      ),
    );
  });
});
