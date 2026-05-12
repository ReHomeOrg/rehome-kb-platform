/**
 * /articles/search — поиск с rank+snippet.
 *
 * Server Component. Если `?q=...` есть — делает POST к
 * `/api/v1/articles/search` (через apiFetch); рендерит результаты.
 * Без `q` — пустая форма + hint.
 */

import Nav from "@/app/_components/nav";
import { searchArticles } from "@/lib/api/articles";

import SearchForm from "./_components/search-form";
import SearchResults from "./_components/search-results";

interface PageProps {
  searchParams: Promise<{ q?: string }>;
}

export default async function SearchPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const { q } = await searchParams;
  const trimmed = q?.trim();
  const results = trimmed ? await searchArticles({ q: trimmed }) : null;

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Поиск статей</h1>
          <p className="mt-1 text-sm text-gray-600">
            Полнотекстовый поиск по Postgres FTS (русский стемминг).
          </p>
        </header>
        <SearchForm initial={trimmed ?? ""} />
        {results ? <SearchResults hits={results.data} /> : null}
      </main>
    </>
  );
}
