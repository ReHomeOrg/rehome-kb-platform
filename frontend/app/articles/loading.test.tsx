import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ArticlesLoading from "./loading";

describe("ArticlesLoading skeleton", () => {
  it("renders <main> wrapper", () => {
    const { container } = render(<ArticlesLoading />);
    expect(container.querySelector("main")).toBeInTheDocument();
  });

  it("renders multiple animate-pulse card placeholders", () => {
    const { container } = render(<ArticlesLoading />);
    const pulses = container.querySelectorAll(".animate-pulse");
    // 1 заголовок + 1 hero block + 6 card placeholders
    expect(pulses.length).toBeGreaterThanOrEqual(7);
  });
});
