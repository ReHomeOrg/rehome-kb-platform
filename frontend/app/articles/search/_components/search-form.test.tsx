import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SearchForm from "./search-form";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

describe("SearchForm", () => {
  it("renders empty initial", () => {
    render(<SearchForm />);
    const input = screen.getByPlaceholderText(/сервисный платёж/);
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("submits with trimmed query → router.push", () => {
    pushMock.mockReset();
    render(<SearchForm initial="договор" />);
    const button = screen.getByText("Найти");
    fireEvent.click(button);
    expect(pushMock).toHaveBeenCalledWith(
      "/articles/search?q=%D0%B4%D0%BE%D0%B3%D0%BE%D0%B2%D0%BE%D1%80",
    );
  });

  it("empty submit clears query in URL", () => {
    pushMock.mockReset();
    render(<SearchForm initial="" />);
    fireEvent.click(screen.getByText("Найти"));
    expect(pushMock).toHaveBeenCalledWith("/articles/search");
  });

  it("whitespace-only submit clears query", () => {
    pushMock.mockReset();
    render(<SearchForm initial="   " />);
    fireEvent.click(screen.getByText("Найти"));
    expect(pushMock).toHaveBeenCalledWith("/articles/search");
  });
});
