import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatUnansweredQuery } from "@/lib/api/chat-unanswered";

import UnansweredModerationPanel from "./unanswered-moderation-panel";

const attachMock = vi.fn();
const dismissMock = vi.fn();

vi.mock("@/lib/api/chat-unanswered", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/chat-unanswered")>();
  return {
    ...actual,
    attachChatUnansweredQuery: (...args: unknown[]) => attachMock(...args),
    dismissChatUnansweredQuery: (...args: unknown[]) => dismissMock(...args),
  };
});

function makeRow(over: Partial<ChatUnansweredQuery> = {}): ChatUnansweredQuery {
  return {
    id: "id-1",
    query_masked: "Как продлить договор?",
    author_sub: "user-1",
    chat_session_id: "session-abc",
    status: "NEW",
    attached_question_id: null,
    attached_article_slug: null,
    dismiss_reason: null,
    created_at: "2026-05-29T12:00:00Z",
    attached_at: null,
    updated_at: "2026-05-29T12:00:00Z",
    ...over,
  };
}

describe("UnansweredModerationPanel", () => {
  beforeEach(() => {
    attachMock.mockReset();
    dismissMock.mockReset();
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders empty state when no items", () => {
    render(
      <UnansweredModerationPanel
        initialItems={[]}
        initialTotal={0}
        statusFilter="NEW"
      />,
    );
    expect(screen.getByText(/Очередь пуста/i)).toBeInTheDocument();
  });

  it("renders row with masked query + author + actions for NEW", () => {
    render(
      <UnansweredModerationPanel
        initialItems={[makeRow()]}
        initialTotal={1}
        statusFilter="NEW"
      />,
    );
    expect(screen.getByText(/Как продлить договор/i)).toBeInTheDocument();
    expect(screen.getByText(/user-1/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Привязать/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Отклонить/i })).toBeInTheDocument();
  });

  it("attach button calls API with article slug + override body", async () => {
    const attached = makeRow({
      status: "ATTACHED",
      attached_question_id: "q-9",
      attached_article_slug: "rent-contract",
    });
    attachMock.mockResolvedValue({
      unanswered: attached,
      question: { id: "q-9" },
    });

    render(
      <UnansweredModerationPanel
        initialItems={[makeRow()]}
        initialTotal={1}
        statusFilter="NEW"
      />,
    );

    fireEvent.change(screen.getByLabelText(/Article slug/i), {
      target: { value: "rent-contract" },
    });
    fireEvent.change(screen.getByLabelText(/Question body override/i), {
      target: { value: "Refined question" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Привязать/i }));

    await waitFor(() => {
      expect(attachMock).toHaveBeenCalledWith("id-1", {
        article_slug: "rent-contract",
        question_body: "Refined question",
      });
    });
    // После attach — row меняет status, action UI скрывается.
    await waitFor(() => {
      expect(screen.getByText(/Привязано к статье/i)).toBeInTheDocument();
    });
  });

  it("attach disabled until article slug provided", () => {
    render(
      <UnansweredModerationPanel
        initialItems={[makeRow()]}
        initialTotal={1}
        statusFilter="NEW"
      />,
    );
    const btn = screen.getByRole("button", { name: /Привязать/i });
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Article slug/i), {
      target: { value: "x" },
    });
    expect(btn).not.toBeDisabled();
  });

  it("dismiss button calls API with reason", async () => {
    const dismissed = makeRow({ status: "DISMISSED", dismiss_reason: "late" });
    dismissMock.mockResolvedValue(dismissed);

    render(
      <UnansweredModerationPanel
        initialItems={[makeRow()]}
        initialTotal={1}
        statusFilter="NEW"
      />,
    );

    fireEvent.change(screen.getByLabelText(/Dismiss reason/i), {
      target: { value: "late" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Отклонить/i }));

    await waitFor(() => {
      expect(dismissMock).toHaveBeenCalledWith("id-1", "late");
    });
  });

  it("ATTACHED row shows link to article + Q&A queue", () => {
    render(
      <UnansweredModerationPanel
        initialItems={[
          makeRow({
            status: "ATTACHED",
            attached_question_id: "qid-aaa",
            attached_article_slug: "rent-contract",
          }),
        ]}
        initialTotal={1}
        statusFilter="ATTACHED"
      />,
    );
    expect(
      screen.getByRole("link", { name: /rent-contract/i }),
    ).toHaveAttribute("href", "/articles/rent-contract");
    expect(screen.queryByRole("button", { name: /Привязать/i })).not.toBeInTheDocument();
  });

  it("DISMISSED row shows reason and no action buttons", () => {
    render(
      <UnansweredModerationPanel
        initialItems={[
          makeRow({ status: "DISMISSED", dismiss_reason: "out of scope" }),
        ]}
        initialTotal={1}
        statusFilter="DISMISSED"
      />,
    );
    expect(screen.getByText(/Причина: out of scope/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Привязать/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Отклонить/i })).not.toBeInTheDocument();
  });

  it("status tabs link to NEW/ATTACHED/DISMISSED", () => {
    render(
      <UnansweredModerationPanel
        initialItems={[]}
        initialTotal={0}
        statusFilter="NEW"
      />,
    );
    expect(screen.getByRole("link", { name: "Новые" })).toHaveAttribute(
      "href",
      "/admin/chat-unanswered-queries?status=NEW",
    );
    expect(screen.getByRole("link", { name: "Привязанные" })).toHaveAttribute(
      "href",
      "/admin/chat-unanswered-queries?status=ATTACHED",
    );
    expect(screen.getByRole("link", { name: "Отклонённые" })).toHaveAttribute(
      "href",
      "/admin/chat-unanswered-queries?status=DISMISSED",
    );
  });
});
