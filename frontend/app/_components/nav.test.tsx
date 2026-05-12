import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Nav from "./nav";

const cookieStoreMock = {
  has: vi.fn<(name: string) => boolean>(),
};

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => cookieStoreMock),
}));

describe("Nav", () => {
  it("renders Login link when no session cookie", async () => {
    cookieStoreMock.has.mockReturnValueOnce(false);
    const element = await Nav();
    render(element);
    expect(screen.getByText("Войти")).toBeInTheDocument();
    expect(screen.queryByText("Выйти")).not.toBeInTheDocument();
  });

  it("renders Logout button when session cookie present", async () => {
    cookieStoreMock.has.mockReturnValueOnce(true);
    const element = await Nav();
    render(element);
    expect(screen.getByText("Выйти")).toBeInTheDocument();
    expect(screen.queryByText("Войти")).not.toBeInTheDocument();
  });

  it("renders main nav links", async () => {
    cookieStoreMock.has.mockReturnValueOnce(false);
    const element = await Nav();
    render(element);
    expect(screen.getByText("Главная")).toBeInTheDocument();
    expect(screen.getByText("Статьи")).toBeInTheDocument();
    expect(screen.getByText("Документы")).toBeInTheDocument();
    expect(screen.getByText("Чат")).toBeInTheDocument();
  });
});
