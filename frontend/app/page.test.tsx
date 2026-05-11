import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import Home from "./page";

describe("Home page", () => {
  it("renders the help-center heading", () => {
    render(<Home />);
    expect(
      screen.getByRole("heading", { name: /help\.rehome\.one/i }),
    ).toBeInTheDocument();
  });

  it("renders the coming-soon notice referencing Phase 1 E3", () => {
    render(<Home />);
    expect(screen.getByText(/Coming soon/i)).toBeInTheDocument();
    expect(screen.getByText(/Phase 1, E3/i)).toBeInTheDocument();
  });

  it("renders the description mentioning reHome knowledge base", () => {
    render(<Home />);
    expect(screen.getByText(/База знаний reHome/i)).toBeInTheDocument();
  });
});
