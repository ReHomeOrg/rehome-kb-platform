import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TagFilter from "./tag-filter";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

describe("TagFilter", () => {
  it("submits with trimmed q", () => {
    pushMock.mockReset();
    render(<TagFilter initial="догов" />);
    fireEvent.click(screen.getByText("Найти"));
    expect(pushMock).toHaveBeenCalledWith(
      "/tags?q=" + encodeURIComponent("догов"),
    );
  });

  it("empty submit → bare /tags", () => {
    pushMock.mockReset();
    render(<TagFilter initial="" />);
    fireEvent.click(screen.getByText("Найти"));
    expect(pushMock).toHaveBeenCalledWith("/tags");
  });

  it("whitespace submit → bare /tags", () => {
    pushMock.mockReset();
    render(<TagFilter initial="   " />);
    fireEvent.click(screen.getByText("Найти"));
    expect(pushMock).toHaveBeenCalledWith("/tags");
  });
});
