import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GroupMembersPanel from "./group-members-panel";

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;
const originalConfirm = window.confirm;

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
  window.confirm = originalConfirm;
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const groupFixture = {
  id: "g-1",
  name: "backend-team",
  description: "Production DB + API keys",
  created_by: "user-1",
  created_at: "2026-05-17T00:00:00Z",
};

function memberFixture(userId: string, role: "owner" | "member"): unknown {
  return {
    group_id: "g-1",
    user_id: userId,
    role,
    added_at: "2026-05-17T00:00:00Z",
  };
}

describe("GroupMembersPanel", () => {
  it("показывает empty state когда participants=0", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));
    render(
      <GroupMembersPanel
        groupId="g-1"
        group={groupFixture}
        currentUserId="user-1"
        onBack={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/Участников нет/)).toBeInTheDocument();
    });
  });

  it("показывает список members + 'это вы' пометку", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [
          memberFixture("user-1", "owner"),
          memberFixture("user-2", "member"),
        ],
      }),
    );
    render(
      <GroupMembersPanel
        groupId="g-1"
        group={groupFixture}
        currentUserId="user-1"
        onBack={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/это вы/)).toBeInTheDocument();
    });
    expect(screen.getAllByText(/user-/).length).toBeGreaterThan(0);
  });

  it("non-owner не видит форму добавления", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ data: [memberFixture("user-1", "member")] }),
    );
    render(
      <GroupMembersPanel
        groupId="g-1"
        group={groupFixture}
        currentUserId="user-1"
        onBack={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/это вы/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Добавить участника/)).toBeNull();
  });

  it("owner видит форму добавления + happy add path", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ data: [memberFixture("user-1", "owner")] }),
      )
      // Add → 201
      .mockResolvedValueOnce(jsonResponse(memberFixture("user-2", "member"), 201))
      // Reload
      .mockResolvedValueOnce(
        jsonResponse({
          data: [
            memberFixture("user-1", "owner"),
            memberFixture("user-2", "member"),
          ],
        }),
      );

    render(
      <GroupMembersPanel
        groupId="g-1"
        group={groupFixture}
        currentUserId="user-1"
        onBack={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/Добавить участника/)).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText(/User ID/), {
      target: { value: "user-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));
    await waitFor(() => {
      const call = fetchMock.mock.calls[1]!;
      expect(call[0]).toBe("/api/kb/api/v1/vault/groups/g-1/members");
      expect((call[1] as RequestInit).method).toBe("POST");
    });
    const body = JSON.parse(
      (fetchMock.mock.calls[1]![1] as RequestInit).body as string,
    );
    expect(body).toEqual({ user_id: "user-2", role: "member" });
  });

  it("owner remove member: confirm → DELETE + reload", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          data: [
            memberFixture("user-1", "owner"),
            memberFixture("user-2", "member"),
          ],
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(
        jsonResponse({ data: [memberFixture("user-1", "owner")] }),
      );

    window.confirm = vi.fn().mockReturnValue(true);

    render(
      <GroupMembersPanel
        groupId="g-1"
        group={groupFixture}
        currentUserId="user-1"
        onBack={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText(/это вы/)).toBeInTheDocument();
    });
    // Только member user-2 имеет Убрать (self не показывает).
    fireEvent.click(screen.getByRole("button", { name: "Убрать" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls[1]![0]).toBe(
        "/api/kb/api/v1/vault/groups/g-1/members/user-2",
      );
      expect((fetchMock.mock.calls[1]![1] as RequestInit).method).toBe(
        "DELETE",
      );
    });
  });

  it("404 от list → отображает alert", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Group not found" }, 404),
    );
    render(
      <GroupMembersPanel
        groupId="g-1"
        group={null}
        currentUserId="user-1"
        onBack={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/404/);
    });
  });
});
