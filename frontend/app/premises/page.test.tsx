import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PremisesPage from "./page";
import { getSessionAccess } from "@/lib/auth/access";
import { listPremises, searchPremises } from "@/lib/api/premises";

vi.mock("@/app/_components/nav", () => ({
  default: () => <nav data-testid="nav" />,
}));
vi.mock("@/lib/auth/access", () => ({
  getSessionAccess: vi.fn(),
}));
vi.mock("@/lib/api/premises", () => ({
  listPremises: vi.fn(),
  searchPremises: vi.fn(),
}));

const mockAccess = vi.mocked(getSessionAccess);
const mockList = vi.mocked(listPremises);

afterEach(() => vi.clearAllMocks());

describe("PremisesPage gate", () => {
  it("незалогиненному показывает приглашение войти и НЕ зовёт API", async () => {
    mockAccess.mockResolvedValue({ isLoggedIn: false, isStaffAdmin: false });
    render(await PremisesPage({ searchParams: Promise.resolve({}) }));
    expect(
      screen.getByText("Для просмотра, пожалуйста, авторизуйтесь"),
    ).toBeInTheDocument();
    expect(mockList).not.toHaveBeenCalled();
    expect(vi.mocked(searchPremises)).not.toHaveBeenCalled();
  });

  it("залогиненному рендерит каталог (без приглашения)", async () => {
    mockAccess.mockResolvedValue({ isLoggedIn: true, isStaffAdmin: false });
    mockList.mockResolvedValue({
      data: [],
      pagination: { cursor_next: null, has_more: false },
    });
    render(await PremisesPage({ searchParams: Promise.resolve({}) }));
    expect(
      screen.queryByText("Для просмотра, пожалуйста, авторизуйтесь"),
    ).not.toBeInTheDocument();
    expect(mockList).toHaveBeenCalledOnce();
  });
});
