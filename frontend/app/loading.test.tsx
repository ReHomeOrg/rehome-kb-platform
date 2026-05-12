import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Loading from "./loading";

describe("Loading skeleton", () => {
  it("renders pulse skeletons", () => {
    const { container } = render(<Loading />);
    const pulses = container.querySelectorAll(".animate-pulse");
    expect(pulses.length).toBeGreaterThan(0);
  });

  it("renders nav-less placeholder (no specific content)", () => {
    const { container } = render(<Loading />);
    // Структура — main + skeleton blocks, no real text content.
    expect(container.querySelector("main")).toBeInTheDocument();
  });
});
