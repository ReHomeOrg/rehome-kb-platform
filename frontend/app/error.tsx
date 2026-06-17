"use client";

/**
 * Global error boundary (UI.6 #85) — Next.js convention.
 *
 * Reset button перерендеривает дочернее дерево. error.message НЕ
 * exposes в production (может содержать stack trace / sensitive
 * details). В dev — показываем для отладки.
 */

import { useEffect } from "react";

interface ErrorBoundaryProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function ErrorBoundary({
  error,
  reset,
}: ErrorBoundaryProps): JSX.Element {
  useEffect(() => {
    // Server-side Next.js логирует error автоматически.
    // Client-side — console.error для dev debug.
    console.error("UI error boundary:", error);
  }, [error]);

  const isDev = process.env.NODE_ENV !== "production";

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-12 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">
        Что-то пошло не так
      </h1>
      <p className="text-sm text-gray-600">
        Произошла ошибка. Попробуйте обновить страницу или вернуться позже.
      </p>
      {isDev ? (
        <pre className="overflow-auto rounded bg-gray-50 p-3 text-left text-xs text-red-700">
          {error.message}
          {error.digest ? `\nDigest: ${error.digest}` : ""}
        </pre>
      ) : null}
      <button
        type="button"
        onClick={reset}
        className="mx-auto rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-hover"
      >
        Попробовать снова
      </button>
    </main>
  );
}
