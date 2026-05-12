/**
 * Loading skeleton для /documents* routes (UI.6 #85).
 */

export default function DocumentsLoading(): JSX.Element {
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
      <div className="h-7 w-40 animate-pulse rounded bg-gray-200" />
      <div className="h-24 animate-pulse rounded-md border border-gray-200 bg-gray-50" />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-28 animate-pulse rounded-md border border-gray-200 bg-gray-50"
          />
        ))}
      </div>
    </main>
  );
}
