import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CollaboratorsSection from "./collaborators-section";

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

function rowFixture(over: Partial<Record<string, unknown>> = {}): unknown {
  return {
    id: "row-1",
    collaborator_id: "collab-1",
    role: "default_uk",
    priority: 1,
    notes: null,
    assigned_at: "2026-05-17T00:00:00Z",
    assigned_by: "staff-x",
    collaborator: {
      id: "collab-1",
      type: "management_company",
      brand_name: "УК Centrum",
      financial_group: "D",
      status: "ACTIVE",
      service_area: "Москва",
      working_hours: null,
      website: null,
      rating: null,
    },
    ...over,
  };
}

describe("CollaboratorsSection", () => {
  it("отображает empty state когда нет назначений", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));
    render(<CollaboratorsSection premisesId="p-1" canManage={false} />);
    await waitFor(() => {
      expect(screen.getByText(/Назначений нет/)).toBeInTheDocument();
    });
  });

  it("рендерит список назначений с brand_name и role", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ data: [rowFixture(), rowFixture({ id: "row-2", role: "plumber" })] }),
    );
    render(<CollaboratorsSection premisesId="p-1" canManage={false} />);
    await waitFor(() => {
      expect(screen.getAllByText("УК Centrum")).toHaveLength(2);
    });
    expect(screen.getByText(/default_uk · приоритет 1/)).toBeInTheDocument();
    expect(screen.getByText(/plumber · приоритет 1/)).toBeInTheDocument();
  });

  it("canManage=false → нет кнопок Назначить/Убрать", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [rowFixture()] }));
    render(<CollaboratorsSection premisesId="p-1" canManage={false} />);
    await waitFor(() => {
      expect(screen.getByText("УК Centrum")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: /Назначить/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Убрать" })).toBeNull();
  });

  it("canManage=true → показывает кнопки + раскрывает форму", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ data: [] }));
    render(<CollaboratorsSection premisesId="p-1" canManage />);
    await waitFor(() => {
      expect(screen.getByText(/Назначений нет/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "+ Назначить" }));
    expect(screen.getByLabelText(/ID коллаборанта/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Назначить" })).toBeInTheDocument();
  });

  it("assign happy path → POST + reload", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ data: [] }))
      .mockResolvedValueOnce(new Response(null, { status: 201 }))
      .mockResolvedValueOnce(jsonResponse({ data: [rowFixture()] }));

    render(<CollaboratorsSection premisesId="p-1" canManage />);
    await waitFor(() =>
      expect(screen.getByText(/Назначений нет/)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "+ Назначить" }));
    fireEvent.change(screen.getByLabelText(/ID коллаборанта/), {
      target: { value: "collab-1" },
    });
    fireEvent.change(screen.getByLabelText(/Role/), {
      target: { value: "default_uk" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Назначить" }));

    await waitFor(() => {
      // POST call (2nd fetch — index 1)
      expect(fetchMock.mock.calls[1]![0]).toBe(
        "/api/kb/api/v1/premises/p-1/collaborators",
      );
      expect((fetchMock.mock.calls[1]![1] as RequestInit).method).toBe("POST");
    });
    const body = JSON.parse(
      (fetchMock.mock.calls[1]![1] as RequestInit).body as string,
    );
    expect(body).toEqual({
      collaborator_id: "collab-1",
      role: "default_uk",
      priority: 1,
      notes: null,
    });
    // После reload — отображается УК Centrum.
    await waitFor(() => {
      expect(screen.getByText("УК Centrum")).toBeInTheDocument();
    });
  });

  it("remove confirms + DELETE с role query", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ data: [rowFixture()] }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse({ data: [] }));
    window.confirm = vi.fn().mockReturnValue(true);

    render(<CollaboratorsSection premisesId="p-1" canManage />);
    await waitFor(() => {
      expect(screen.getByText("УК Centrum")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "Убрать" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls[1]![0]).toBe(
        "/api/kb/api/v1/premises/p-1/collaborators/collab-1?role=default_uk",
      );
      expect((fetchMock.mock.calls[1]![1] as RequestInit).method).toBe(
        "DELETE",
      );
    });
  });

  it("assign 409 (UQ violation) → отображает ошибку без reload", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ data: [] }))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Already assigned" }, 409),
      );

    render(<CollaboratorsSection premisesId="p-1" canManage />);
    await waitFor(() =>
      expect(screen.getByText(/Назначений нет/)).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "+ Назначить" }));
    fireEvent.change(screen.getByLabelText(/ID коллаборанта/), {
      target: { value: "collab-1" },
    });
    fireEvent.change(screen.getByLabelText(/Role/), {
      target: { value: "default_uk" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Назначить" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /409: Already assigned/,
      );
    });
    // fetch count = 2 (initial list + failed POST); никакого reload.
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
