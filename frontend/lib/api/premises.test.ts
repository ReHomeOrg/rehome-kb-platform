import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";
import { getPremisesCard, listPremises, searchPremises } from "./premises";

vi.mock("./client", () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));

const apiFetchMock = vi.mocked(apiFetch);

describe("premises API", () => {
  afterEach(() => apiFetchMock.mockReset());

  it("listPremises без фильтров — clean URL", async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [],
      pagination: { cursor_next: null, has_more: false },
    });
    await listPremises();
    expect(apiFetchMock).toHaveBeenCalledWith("/api/v1/premises-cards");
  });

  it("listPremises cursor + limit → encode'ит в URL", async () => {
    apiFetchMock.mockResolvedValueOnce({
      data: [],
      pagination: { cursor_next: null, has_more: false },
    });
    await listPremises({ cursor: "abc", limit: 50 });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain("cursor=abc");
    expect(url).toContain("limit=50");
  });

  it("getPremisesCard encode'ит slug для URL safety", async () => {
    apiFetchMock.mockResolvedValueOnce({} as never);
    await getPremisesCard("spb/test");
    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/premises-cards/spb%2Ftest",
    );
  });

  it("searchPremises POSTs body с q + limit", async () => {
    apiFetchMock.mockResolvedValueOnce({ data: [] });
    await searchPremises({ q: "санкт-петербург", limit: 30 });
    const [path, opts] = apiFetchMock.mock.calls[0];
    expect(path).toBe("/api/v1/premises-cards/search");
    expect((opts as RequestInit).method).toBe("POST");
    const body = JSON.parse((opts as RequestInit).body as string);
    expect(body).toEqual({ q: "санкт-петербург", limit: 30 });
  });
});
