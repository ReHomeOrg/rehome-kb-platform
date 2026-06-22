import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RehomeIdpButton } from "./rehome-idp-button";

afterEach(() => {
  vi.unstubAllEnvs();
});

const LABEL = "Авторизация в rehome";

describe("RehomeIdpButton", () => {
  it("рендерит кнопку с kc_idp_hint при заданном allowlisted alias", () => {
    vi.stubEnv("NEXT_PUBLIC_REHOME_IDP_HINT", "rehome");
    render(<RehomeIdpButton />);
    const btn = screen.getByText(LABEL);
    expect(btn).toBeInTheDocument();
    expect(btn.getAttribute("href")).toContain(
      "/api/auth/login?kc_idp_hint=rehome",
    );
  });

  it("возвращает null без флага (прод-сборка — кнопки нет)", () => {
    vi.stubEnv("NEXT_PUBLIC_REHOME_IDP_HINT", undefined as unknown as string);
    const { container } = render(<RehomeIdpButton />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText(LABEL)).not.toBeInTheDocument();
  });

  it("возвращает null при значении вне allowlist (анти-param-injection)", () => {
    vi.stubEnv("NEXT_PUBLIC_REHOME_IDP_HINT", "evil");
    const { container } = render(<RehomeIdpButton />);
    expect(container).toBeEmptyDOMElement();
  });
});
