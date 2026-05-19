import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/admin-users";
import type { KbUser } from "@/lib/api/types";

import KbUserEditForm from "./kb-user-edit-form";

const pushMock = vi.fn();
const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock }),
}));

const patchMock = vi.spyOn(api, "patchKbUser");
const deactivateMock = vi.spyOn(api, "deactivateKbUser");

function makeUser(overrides: Partial<KbUser> = {}): KbUser {
  return {
    id: "user-abc",
    email: "admin@example.com",
    full_name: "Иван Админов",
    role: "staff_admin",
    permissions: [],
    status: "ACTIVE",
    created_at: "2026-01-01T00:00:00Z",
    last_login_at: "2026-05-01T12:00:00Z",
    mfa_enabled: true,
    ...overrides,
  };
}

beforeEach(() => {
  pushMock.mockReset();
  refreshMock.mockReset();
  patchMock.mockReset();
  deactivateMock.mockReset();
});

afterEach(() => {
  patchMock.mockReset();
  deactivateMock.mockReset();
});

describe("KbUserEditForm", () => {
  it("renders identification + role/status selects", () => {
    render(<KbUserEditForm initial={makeUser()} />);
    expect(screen.getByText("admin@example.com")).toBeInTheDocument();
    const role = screen.getByLabelText(/Role/) as HTMLSelectElement;
    expect(role.value).toBe("staff_admin");
  });

  it("no PATCH when nothing changed", async () => {
    render(<KbUserEditForm initial={makeUser()} />);
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(patchMock).not.toHaveBeenCalled();
    });
  });

  it("sends PATCH with changed role", async () => {
    patchMock.mockResolvedValueOnce(makeUser({ role: "staff_legal" }));
    render(<KbUserEditForm initial={makeUser()} />);
    fireEvent.change(screen.getByLabelText(/Role/), {
      target: { value: "staff_legal" },
    });
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith("user-abc", { role: "staff_legal" });
    });
    expect(pushMock).toHaveBeenCalledWith("/admin/users");
  });

  it("splits permissions textarea by newline", async () => {
    patchMock.mockResolvedValueOnce(makeUser());
    render(<KbUserEditForm initial={makeUser()} />);
    fireEvent.change(screen.getByLabelText(/Permissions/), {
      target: { value: "p1\np2\n  p3  \n\n" },
    });
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith("user-abc", {
        permissions: ["p1", "p2", "p3"],
      });
    });
  });

  it("hides Deactivate when status=ARCHIVED", () => {
    render(<KbUserEditForm initial={makeUser({ status: "ARCHIVED" })} />);
    expect(screen.queryByText("Деактивировать")).not.toBeInTheDocument();
  });

  it("deactivate calls DELETE after confirm", async () => {
    deactivateMock.mockResolvedValueOnce(undefined);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<KbUserEditForm initial={makeUser()} />);
    fireEvent.click(screen.getByText("Деактивировать"));
    await waitFor(() => {
      expect(deactivateMock).toHaveBeenCalledWith("user-abc");
    });
    expect(pushMock).toHaveBeenCalledWith("/admin/users");
    confirmSpy.mockRestore();
  });

  it("deactivate aborts if user cancels confirm", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<KbUserEditForm initial={makeUser()} />);
    fireEvent.click(screen.getByText("Деактивировать"));
    expect(deactivateMock).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
