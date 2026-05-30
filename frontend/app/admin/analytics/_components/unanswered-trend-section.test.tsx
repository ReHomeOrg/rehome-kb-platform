import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { UnansweredTrend } from "@/lib/api/admin-analytics";

import UnansweredTrendSection from "./unanswered-trend-section";

function makeRow(over: Partial<UnansweredTrend> = {}): UnansweredTrend {
  return {
    normalized_query: "страховой полис",
    count: 3,
    first_seen: "2026-05-28T10:00:00Z",
    last_seen: "2026-05-29T12:00:00Z",
    ...over,
  };
}

describe("UnansweredTrendSection", () => {
  it("рендерит empty state когда нет данных", () => {
    render(<UnansweredTrendSection data={[]} windowHours={24} />);
    expect(
      screen.getByText(/Нет необработанных запросов/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/window=24/i)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("рендерит table со строками, нормализованный query в первой ячейке", () => {
    const rows = [
      makeRow({ normalized_query: "страховой полис", count: 7 }),
      makeRow({ normalized_query: "кэдо", count: 2 }),
    ];
    render(<UnansweredTrendSection data={rows} windowHours={168} />);

    const table = screen.getByRole("table");
    const body = within(table).getAllByRole("rowgroup")[1];
    const bodyRows = within(body).getAllByRole("row");
    expect(bodyRows).toHaveLength(2);

    expect(within(bodyRows[0]).getByText("страховой полис")).toBeInTheDocument();
    expect(within(bodyRows[0]).getByText("7")).toBeInTheDocument();
    expect(within(bodyRows[1]).getByText("кэдо")).toBeInTheDocument();
  });

  it("count >= 5 подсвечен hot-стилем, count < 5 — нет", () => {
    render(
      <UnansweredTrendSection
        data={[
          makeRow({ normalized_query: "горячий", count: 5 }),
          makeRow({ normalized_query: "тёплый", count: 4 }),
        ]}
        windowHours={24}
      />,
    );
    const hot = screen.getByText("5");
    const warm = screen.getByText("4");
    expect(hot.className).toContain("text-red-700");
    expect(warm.className).not.toContain("text-red-700");
  });

  it("ссылка «Очередь модерации» ведёт на queue со status=NEW", () => {
    render(<UnansweredTrendSection data={[]} windowHours={24} />);
    const link = screen.getByRole("link", { name: /Очередь модерации/i });
    expect(link).toHaveAttribute(
      "href",
      "/admin/chat-unanswered-queries?status=NEW",
    );
  });

  it("форматирует first_seen / last_seen через ru-RU Intl", () => {
    render(
      <UnansweredTrendSection
        data={[
          makeRow({
            normalized_query: "контракт",
            count: 1,
            first_seen: "2026-05-28T10:00:00Z",
            last_seen: "2026-05-29T12:00:00Z",
          }),
        ]}
        windowHours={24}
      />,
    );
    // ru-RU dd.MM, HH:mm — формат стабилен, но конкретное время зависит от TZ.
    // Проверяем что обе даты присутствуют через month delimiter.
    const dots = screen.getAllByText(/\d{2}\.\d{2}/);
    expect(dots.length).toBeGreaterThanOrEqual(2);
  });
});
