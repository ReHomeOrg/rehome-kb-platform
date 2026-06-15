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

  it("прячет Кадры/Вебхуки/Админ от незалогиненного", async () => {
    cookieStoreMock.has.mockReturnValueOnce(false);
    render(await Nav());
    expect(screen.queryByText("Кадры")).not.toBeInTheDocument();
    expect(screen.queryByText("Вебхуки")).not.toBeInTheDocument();
    expect(screen.queryByText("Админ")).not.toBeInTheDocument();
    // англоязычные старые подписи тоже не должны просочиться
    expect(screen.queryByText("Webhooks")).not.toBeInTheDocument();
    expect(screen.queryByText("Admin")).not.toBeInTheDocument();
  });

  it("показывает Кадры/Вебхуки/Админ залогиненному", async () => {
    cookieStoreMock.has.mockReturnValueOnce(true);
    render(await Nav());
    expect(screen.getByText("Кадры")).toBeInTheDocument();
    expect(screen.getByText("Вебхуки")).toBeInTheDocument();
    expect(screen.getByText("Админ")).toBeInTheDocument();
  });
});
