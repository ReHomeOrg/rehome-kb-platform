import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Article } from "@/lib/api/types";

import ArticleForm from "./article-form";

const pushMock = vi.fn();
const refreshMock = vi.fn();
const backMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock, back: backMock }),
}));

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  pushMock.mockReset();
  refreshMock.mockReset();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

function articleFixture(): Article {
  return {
    id: "art-1",
    slug: "onboarding-guide",
    title: "Гайд по онбордингу",
    summary: null,
    body_markdown: "# Привет\n\nКонтент",
    category: "onboarding",
    audience: "tenant",
    language: "ru",
    tags: ["onboarding", "tenant"],
    access_level: "PUBLIC",
    status: "PUBLISHED",
    published_at: "2026-05-17T00:00:00Z",
    created_at: "2026-05-17T00:00:00Z",
    updated_at: "2026-05-17T00:00:00Z",
  };
}

function fillRequired(): void {
  fireEvent.change(screen.getByLabelText(/Slug/), {
    target: { value: "test-article" },
  });
  fireEvent.change(screen.getByLabelText(/Заголовок/), {
    target: { value: "Тестовая статья" },
  });
  fireEvent.change(screen.getByLabelText(/Категория/), {
    target: { value: "faq" },
  });
  fireEvent.change(screen.getByLabelText(/Содержание/), {
    target: { value: "# Title\n\nContent" },
  });
}

describe("ArticleForm (create)", () => {
  it("показывает Создать в режиме create", () => {
    render(<ArticleForm />);
    expect(screen.getByRole("button", { name: "Создать" })).toBeInTheDocument();
  });

  it("happy path → POST /articles + push на slug", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ slug: "test-article", title: "Тестовая статья" }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<ArticleForm />);
    fillRequired();
    fireEvent.change(screen.getByLabelText(/Тэги/), {
      target: { value: "  faq , onboarding ,  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/kb/api/v1/articles",
        expect.objectContaining({ method: "POST" }),
      );
    });
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as RequestInit).body as string,
    );
    expect(body.slug).toBe("test-article");
    expect(body.title).toBe("Тестовая статья");
    expect(body.category).toBe("faq");
    expect(body.access_level).toBe("PUBLIC");
    expect(body.tags).toEqual(["faq", "onboarding"]); // trimmed + filtered empty
    expect(body.status).toBe("DRAFT");
    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/articles/test-article");
    });
  });

  it("backend 409 (slug conflict) → отображает status + detail", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Slug exists" }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(<ArticleForm />);
    fillRequired();
    fireEvent.click(screen.getByRole("button", { name: "Создать" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/409: Slug exists/);
    });
    expect(pushMock).not.toHaveBeenCalled();
  });
});

describe("ArticleForm (edit)", () => {
  it("в edit mode показывает Сохранить + initial values + immutable disabled", () => {
    render(<ArticleForm initial={articleFixture()} />);
    expect(
      screen.getByRole("button", { name: "Сохранить" }),
    ).toBeInTheDocument();
    expect(
      (screen.getByLabelText(/Заголовок/) as HTMLInputElement).value,
    ).toBe("Гайд по онбордингу");
    // immutable fields disabled
    expect(screen.getByLabelText(/Slug/)).toBeDisabled();
    expect(screen.getByLabelText(/Категория/)).toBeDisabled();
    expect(screen.getByLabelText(/Access level/)).toBeDisabled();
  });

  it("happy edit → PATCH с patchable fields only", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ slug: "onboarding-guide" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<ArticleForm initial={articleFixture()} />);
    fireEvent.change(screen.getByLabelText(/Заголовок/), {
      target: { value: "Гайд по онбордингу — v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/kb/api/v1/articles/onboarding-guide",
        expect.objectContaining({ method: "PATCH" }),
      );
    });
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as RequestInit).body as string,
    );
    expect(body).toEqual({
      title: "Гайд по онбордингу — v2",
      body_markdown: "# Привет\n\nКонтент",
      tags: ["onboarding", "tenant"],
      status: "PUBLISHED",
    });
    // PATCH тело не содержит slug / category / access_level / audience / language.
    expect(body.slug).toBeUndefined();
    expect(body.access_level).toBeUndefined();
  });
});
