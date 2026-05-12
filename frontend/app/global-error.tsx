"use client";

/**
 * Critical error fallback (UI.6 #85) — когда падает root layout.tsx.
 *
 * Next.js конвенция: global-error.tsx ДОЛЖЕН рендерить <html><body>
 * (layout.tsx упал, нет parent shell'а).
 *
 * НЕ показываем error.message в production.
 */

interface GlobalErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({
  error,
  reset,
}: GlobalErrorProps): JSX.Element {
  const isDev = process.env.NODE_ENV !== "production";
  return (
    <html lang="ru">
      <body className="antialiased min-h-screen bg-white text-gray-900">
        <main className="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-12 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">
            Критическая ошибка
          </h1>
          <p className="text-sm text-gray-600">
            Не удалось загрузить приложение. Попробуйте позже.
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
            className="mx-auto rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800"
          >
            Перезагрузить
          </button>
        </main>
      </body>
    </html>
  );
}
