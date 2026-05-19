import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/admin-security-incidents";
import type { SecurityIncident } from "@/lib/api/types";

import IncidentEditForm from "./incident-edit-form";

const pushMock = vi.fn();
const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock }),
}));

const patchMock = vi.spyOn(api, "patchSecurityIncident");

function makeIncident(overrides: Partial<SecurityIncident> = {}): SecurityIncident {
  return {
    id: "abc-123",
    incident_type: "access_violation",
    severity: "high",
    status: "OPEN",
    detected_at: "2026-05-01T12:00:00Z",
    detected_by: "audit",
    affected_resources: [],
    rkn_notification_required: true,
    rkn_notified_at: null,
    resolution_note: null,
    resolved_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  pushMock.mockReset();
  refreshMock.mockReset();
  patchMock.mockReset();
});

afterEach(() => {
  patchMock.mockReset();
});

describe("IncidentEditForm", () => {
  it("renders identification block + status select", () => {
    render(<IncidentEditForm initial={makeIncident()} />);
    expect(screen.getByText("access_violation")).toBeInTheDocument();
    expect(screen.getByLabelText(/Status/)).toBeInTheDocument();
  });

  it("renders RKN datetime input ONLY when notification required", () => {
    const { rerender } = render(
      <IncidentEditForm
        initial={makeIncident({ rkn_notification_required: false })}
      />,
    );
    expect(screen.queryByLabelText(/RKN/)).not.toBeInTheDocument();

    rerender(
      <IncidentEditForm
        initial={makeIncident({ rkn_notification_required: true })}
      />,
    );
    expect(screen.getByLabelText(/RKN/)).toBeInTheDocument();
  });

  it("no-op when nothing changed — no PATCH call", async () => {
    render(<IncidentEditForm initial={makeIncident()} />);
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(patchMock).not.toHaveBeenCalled();
    });
  });

  it("sends PATCH с изменённым status", async () => {
    patchMock.mockResolvedValueOnce(makeIncident({ status: "INVESTIGATING" }));
    render(<IncidentEditForm initial={makeIncident()} />);
    fireEvent.change(screen.getByLabelText(/Status/), {
      target: { value: "INVESTIGATING" },
    });
    fireEvent.click(screen.getByText("Сохранить"));
    await waitFor(() => {
      expect(patchMock).toHaveBeenCalledWith("abc-123", {
        status: "INVESTIGATING",
      });
    });
    expect(pushMock).toHaveBeenCalledWith("/admin/security-incidents");
  });

  it("warning when reverting terminal → non-terminal", () => {
    render(<IncidentEditForm initial={makeIncident({ status: "RESOLVED" })} />);
    fireEvent.change(screen.getByLabelText(/Status/), {
      target: { value: "OPEN" },
    });
    expect(screen.getByText(/409.*reverse/i)).toBeInTheDocument();
  });
});
