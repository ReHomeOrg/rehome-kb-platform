/**
 * Search input (client component) для /premises (#160).
 *
 * Submits как query param `?q=...` через native form GET — page'у
 * Server Component не нужен JS handler.
 */

export default function SearchForm({
  initialQuery,
}: {
  initialQuery: string;
}): JSX.Element {
  return (
    <form method="get" action="/premises" className="flex items-center gap-2">
      <label htmlFor="q" className="sr-only">
        Поиск по адресу или кадастровому номеру
      </label>
      <input
        id="q"
        type="search"
        name="q"
        defaultValue={initialQuery}
        placeholder="Адрес или кадастровый номер"
        className="w-full max-w-md rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-brand focus:outline-none"
      />
      <button
        type="submit"
        className="rounded-md bg-brand px-3 py-1.5 text-sm text-ink hover:bg-brand-hover"
      >
        Найти
      </button>
    </form>
  );
}
