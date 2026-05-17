import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import OnboardingForm from "./onboarding-form";

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

function fillRequired(): void {
  fireEvent.change(screen.getByLabelText(/Юр\. название/), {
    target: { value: "ООО Тест" },
  });
  fireEvent.change(screen.getByLabelText(/География работы/), {
    target: { value: "Москва" },
  });
}

describe("OnboardingForm", () => {
  it("по умолчанию не показывает success state", () => {
    render(<OnboardingForm />);
    expect(screen.queryByText(/Заявка отправлена/)).toBeNull();
    expect(
      screen.getByRole("button", { name: /Отправить заявку/ }),
    ).toBeInTheDocument();
  });

  it("'other' type не доступен в select (ADR-0015 §6)", () => {
    render(<OnboardingForm />);
    const select = screen.getByLabelText(/Тип услуг/) as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).not.toContain("other");
    expect(optionValues).toContain("management_company");
    expect(optionValues).toContain("cleaning");
  });

  it("submit без контакта показывает local error и не вызывает fetch", async () => {
    render(<OnboardingForm />);
    fillRequired();
    fireEvent.submit(screen.getByRole("button", { name: /Отправить/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/хотя бы один контакт/);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("happy path — POST /onboarding и success state", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "anon-id",
          status: "PENDING_REVIEW",
          message: "Заявка принята",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<OnboardingForm />);
    fillRequired();
    fireEvent.change(screen.getByLabelText(/Email/), {
      target: { value: "test@example.com" },
    });
    fireEvent.submit(screen.getByRole("button", { name: /Отправить/ }));

    await waitFor(() => {
      expect(screen.getByText(/Заявка отправлена/)).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/kb/api/v1/collaborators/onboarding",
      expect.objectContaining({ method: "POST" }),
    );
    const body = JSON.parse(
      (fetchMock.mock.calls[0]![1] as RequestInit).body as string,
    );
    expect(body.name).toBe("ООО Тест");
    expect(body.service_area).toBe("Москва");
    expect(body.contact.email).toBe("test@example.com");
    expect(body.contact.phone).toBeNull();
    expect(body.portal_access_level_requested).toBe("LIGHT");
    expect(body.type).toBe("management_company");
  });

  it("429 → отдельное сообщение о rate-limit", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Too many" }), {
        status: 429,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(<OnboardingForm />);
    fillRequired();
    fireEvent.change(screen.getByLabelText(/Телефон/), {
      target: { value: "+71234567890" },
    });
    fireEvent.submit(screen.getByRole("button", { name: /Отправить/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /Слишком много заявок/,
      );
    });
    expect(screen.queryByText(/Заявка отправлена/)).toBeNull();
  });

  it("422 → показывает detail из backend", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "type='other' требует staff_invite" }),
        { status: 422, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<OnboardingForm />);
    fillRequired();
    fireEvent.change(screen.getByLabelText(/Email/), {
      target: { value: "x@example.com" },
    });
    fireEvent.submit(screen.getByRole("button", { name: /Отправить/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/требует staff_invite/);
    });
  });
});
