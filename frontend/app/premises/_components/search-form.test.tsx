import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SearchForm from "./search-form";

describe("SearchForm (premises)", () => {
  it("renders sr-only label с описанием поиска", () => {
    render(<SearchForm initialQuery="" />);
    // Label visually hidden, но доступен через accessible-name.
    expect(
      screen.getByLabelText(/Поиск по адресу или кадастровому номеру/i),
    ).toBeInTheDocument();
  });

  it("renders search input с placeholder", () => {
    render(<SearchForm initialQuery="" />);
    const input = screen.getByPlaceholderText(/Адрес или кадастровый номер/i);
    expect(input).toBeInTheDocument();
    expect(input).toHaveAttribute("type", "search");
    expect(input).toHaveAttribute("name", "q");
  });

  it("renders submit button «Найти»", () => {
    render(<SearchForm initialQuery="" />);
    expect(screen.getByRole("button", { name: "Найти" })).toBeInTheDocument();
  });

  it("preserves initialQuery как defaultValue", () => {
    render(<SearchForm initialQuery="ул. Ленина 5" />);
    const input = screen.getByPlaceholderText(
      /Адрес или кадастровый номер/i,
    ) as HTMLInputElement;
    expect(input.defaultValue).toBe("ул. Ленина 5");
  });

  it("form submits как GET на /premises", () => {
    const { container } = render(<SearchForm initialQuery="" />);
    const form = container.querySelector("form");
    expect(form?.method.toLowerCase()).toBe("get");
    expect(form?.getAttribute("action")).toBe("/premises");
  });
});
