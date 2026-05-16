import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GlobalError from "./global-error";

// global-error.tsx рендерит <html><body> — это требование Next.js
// конвенции (он замещает root layout при критической ошибке). RTL
// нормально pearl'нёт nested html/body — React выдаст warning, но
// мы тестируем именно рендеринг, а не валидность DOM-tree.
beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("GlobalError", () => {
  it("renders user-friendly заголовок + копию", () => {
    render(<GlobalError error={new Error("boom")} reset={vi.fn()} />);
    expect(screen.getByText("Критическая ошибка")).toBeInTheDocument();
    expect(screen.getByText(/Не удалось загрузить/)).toBeInTheDocument();
  });

  it("показывает кнопку «Перезагрузить» и вызывает reset на клик", () => {
    const reset = vi.fn();
    render(<GlobalError error={new Error("x")} reset={reset} />);
    fireEvent.click(screen.getByRole("button", { name: "Перезагрузить" }));
    expect(reset).toHaveBeenCalledOnce();
  });

  it("в dev-режиме показывает error.message + digest", () => {
    // jsdom default NODE_ENV='test' → isDev=true (NODE_ENV !== production).
    render(
      <GlobalError
        error={Object.assign(new Error("dev-stacktrace"), { digest: "abc-123" })}
        reset={vi.fn()}
      />,
    );
    expect(screen.getByText(/dev-stacktrace/)).toBeInTheDocument();
    expect(screen.getByText(/Digest: abc-123/)).toBeInTheDocument();
  });

  it("в production режиме скрывает stacktrace", () => {
    vi.stubEnv("NODE_ENV", "production");
    try {
      const { container } = render(
        <GlobalError
          error={Object.assign(new Error("secret-internal"), { digest: "prod-d" })}
          reset={vi.fn()}
        />,
      );
      expect(container.textContent).not.toContain("secret-internal");
      expect(container.textContent).not.toContain("prod-d");
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("в dev-режиме без digest не печатает «Digest:» строку", () => {
    render(<GlobalError error={new Error("only-msg")} reset={vi.fn()} />);
    expect(screen.getByText(/only-msg/)).toBeInTheDocument();
    expect(screen.queryByText(/Digest:/)).not.toBeInTheDocument();
  });
});
