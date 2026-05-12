/**
 * Loading skeleton для /chat* routes (UI.6 #85).
 */

export default function ChatLoading(): JSX.Element {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-4 px-6 py-8">
      <div className="h-7 w-32 animate-pulse rounded bg-gray-200" />
      <div className="h-10 w-40 animate-pulse rounded-md bg-gray-200" />
      <div className="flex flex-col gap-3">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-12 animate-pulse rounded-md border border-gray-200 bg-gray-50"
          />
        ))}
      </div>
    </main>
  );
}
