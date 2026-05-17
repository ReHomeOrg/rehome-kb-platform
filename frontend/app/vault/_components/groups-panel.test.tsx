import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GroupsPanel from "./groups-panel";

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

function groupFixture(id: string, over: Record<string, unknown> = {}): unknown {
  return {
    id,
    name: `Group ${id}`,
    description: null,
    created_by: "user-1",
    created_at: "2026-05-17T00:00:00Z",
    ...over,
  };
}

describe("GroupsPanel", () => {
  it("empty state когда групп нет", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));
    render(<GroupsPanel currentUserId="user-1" />);
    await waitFor(() => {
      expect(
        screen.getByText(/Вы не состоите ни в одной группе/),
      ).toBeInTheDocument();
    });
  });

  it("показывает список групп с created_by пометкой", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        data: [
          groupFixture("g-1", { name: "backend-team", created_by: "user-1" }),
          groupFixture("g-2", { name: "devops", created_by: "user-2" }),
        ],
      }),
    );
    render(<GroupsPanel currentUserId="user-1" />);
    await waitFor(() => {
      expect(screen.getByText("backend-team")).toBeInTheDocument();
    });
    expect(screen.getByText("devops")).toBeInTheDocument();
    // Только первая группа должна иметь "вы создатель" hint.
    expect(screen.getByText(/вы создатель/)).toBeInTheDocument();
  });

  it("кнопка Создать группу раскрывает форму", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));
    render(<GroupsPanel currentUserId="user-1" />);
    await waitFor(() => {
      expect(screen.getByText(/не состоите/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: /Создать группу/ }));
    expect(screen.getByLabelText(/Название/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Создать" })).toBeInTheDocument();
  });

  it("create happy path → POST + reload показывает новую группу", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ data: [] }))
      .mockResolvedValueOnce(jsonResponse(groupFixture("g-new", { name: "new-team" }), 201))
      .mockResolvedValueOnce(
        jsonResponse({ data: [groupFixture("g-new", { name: "new-team" })] }),
      );

    render(<GroupsPanel currentUserId="user-1" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: /Создать группу/ }));
    fireEvent.change(screen.getByLabelText(/Название/), {
      target: { value: "new-team" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls[1]![0]).toBe("/api/kb/api/v1/vault/groups");
      expect((fetchMock.mock.calls[1]![1] as RequestInit).method).toBe("POST");
    });
    await waitFor(() => {
      expect(screen.getByText("new-team")).toBeInTheDocument();
    });
  });

  it("create 422 → отображает ошибку без reload", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ data: [] }))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "name too short" }, 422),
      );

    render(<GroupsPanel currentUserId="user-1" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: /Создать группу/ }));
    fireEvent.change(screen.getByLabelText(/Название/), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/422/);
    });
    // Не было третьего fetch'а (reload).
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("click на 'Участники' → drill-down в members panel", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ data: [groupFixture("g-1")] }))
      // Группа выбрана → list_members fetch.
      .mockResolvedValueOnce(jsonResponse({ data: [] }));

    render(<GroupsPanel currentUserId="user-1" />);
    await waitFor(() => {
      expect(screen.getByText("Group g-1")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "Участники" }));
    await waitFor(() => {
      expect(
        screen.getByText(/Group g-1 — участники/),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: /К списку групп/ }),
    ).toBeInTheDocument();
  });
});
