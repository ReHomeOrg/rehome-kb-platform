import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ChatLoading from "./loading";

describe("ChatLoading skeleton", () => {
  it("renders <main> wrapper", () => {
    const { container } = render(<ChatLoading />);
    expect(container.querySelector("main")).toBeInTheDocument();
  });

  it("renders animate-pulse placeholders", () => {
    const { container } = render(<ChatLoading />);
    const pulses = container.querySelectorAll(".animate-pulse");
    expect(pulses.length).toBeGreaterThan(0);
  });
});
