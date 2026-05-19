import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/admin-users";
import { ApiError } from "@/lib/api/client";

import KbUserCreateForm from "./kb-user-create-form";

const pushMock = vi.fn();
const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock }),
}));

const createMock = vi.spyOn(api, "createKbUser");

beforeEach(() => {
  pushMock.mockReset();
  refreshMock.mockReset();
  createMock.mockReset();
});

afterEach(() => {
  createMock.mockReset();
});

describe("KbUserCreateForm", () => {
  it("renders required fields", () => {
    render(<KbUserCreateForm />);
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Full name")).toBeInTheDocument();
    expect(screen.getByLabelText("Role")).toBeInTheDocument();
  });

  it("submits POST with required fields", async () => {
    createMock.mockResolvedValueOnce({
      id: "new-id",
      email: "u@example.com",
      full_name: "Test User",
      role: "staff_support",
      permissions: [],
      status: "ACTIVE",
      created_at: "2026-01-01T00:00:00Z",
      last_login_at: null,
      mfa_enabled: false,
    });
    render(<KbUserCreateForm />);
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "u@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Full name"), {
      target: { value: "Test User" },
    });
    fireEvent.click(screen.getByText("Создать"));
    await waitFor(() => {
      expect(createMock).toHaveBeenCalledWith({
        email: "u@example.com",
        full_name: "Test User",
        role: "staff_support",
      });
    });
    expect(pushMock).toHaveBeenCalledWith("/admin/users/new-id");
  });

  it("attaches permissions if non-empty", async () => {
    createMock.mockResolvedValueOnce({
      id: "x",
      email: "u@example.com",
      full_name: "U",
      role: "staff_support",
      permissions: ["p1"],
      status: "ACTIVE",
      created_at: "2026-01-01T00:00:00Z",
      last_login_at: null,
      mfa_enabled: false,
    });
    render(<KbUserCreateForm />);
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "u@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Full name"), {
      target: { value: "U" },
    });
    fireEvent.change(screen.getByLabelText("Permissions"), {
      target: { value: "p1\np2" },
    });
    fireEvent.click(screen.getByText("Создать"));
    await waitFor(() => {
      expect(createMock).toHaveBeenCalledWith({
        email: "u@example.com",
        full_name: "U",
        role: "staff_support",
        permissions: ["p1", "p2"],
      });
    });
  });

  it("shows 409 conflict message", async () => {
    createMock.mockRejectedValueOnce(
      new ApiError(409, { detail: "Email exists" }, "Email exists"),
    );
    render(<KbUserCreateForm />);
    fireEvent.change(screen.getByLabelText("Email"), {
      target: { value: "exists@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Full name"), {
      target: { value: "Existing" },
    });
    fireEvent.click(screen.getByText("Создать"));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/уже существует/);
    });
  });

  it("blocks submit on empty required fields (HTML5 + JS guard)", async () => {
    render(<KbUserCreateForm />);
    // Email + full_name пустые. HTML5 required может block submit; даже если
    // не block — JS guard поймает.
    fireEvent.click(screen.getByText("Создать"));
    await waitFor(() => {
      // either alert или no createMock call.
      expect(createMock).not.toHaveBeenCalled();
    });
  });
});
