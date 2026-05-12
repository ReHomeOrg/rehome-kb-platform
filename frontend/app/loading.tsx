/**
 * Global loading skeleton (UI.6 #85) — для slow Server Components.
 *
 * Next.js рендерит автоматически между навигацией и завершением
 * `async` page component'а.
 */

export default function Loading(): JSX.Element {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-8">
      <div className="h-6 w-1/3 animate-pulse rounded bg-gray-200" />
      <div className="h-4 w-2/3 animate-pulse rounded bg-gray-200" />
      <div className="mt-4 flex flex-col gap-3">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-16 animate-pulse rounded-md border border-gray-200 bg-gray-50"
          />
        ))}
      </div>
    </main>
  );
}
