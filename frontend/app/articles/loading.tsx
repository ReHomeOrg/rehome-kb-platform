/**
 * Loading skeleton для /articles* routes (UI.6 #85).
 */

export default function ArticlesLoading(): JSX.Element {
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
      <div className="h-7 w-32 animate-pulse rounded bg-gray-200" />
      <div className="h-32 animate-pulse rounded-md border border-gray-200 bg-gray-50" />
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className="h-24 animate-pulse rounded-md border border-gray-200 bg-gray-50"
          />
        ))}
      </div>
    </main>
  );
}
