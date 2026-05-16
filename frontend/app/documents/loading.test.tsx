import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DocumentsLoading from "./loading";

describe("DocumentsLoading skeleton", () => {
  it("renders <main> wrapper", () => {
    const { container } = render(<DocumentsLoading />);
    expect(container.querySelector("main")).toBeInTheDocument();
  });

  it("renders animate-pulse card placeholders", () => {
    const { container } = render(<DocumentsLoading />);
    const pulses = container.querySelectorAll(".animate-pulse");
    // 1 заголовок + 1 hero + 4 cards
    expect(pulses.length).toBeGreaterThanOrEqual(6);
  });
});
