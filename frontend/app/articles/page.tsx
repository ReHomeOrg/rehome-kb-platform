/**
 * /articles — список статей с фильтрами + cursor пагинацией.
 *
 * Server Component. Reads URL search params → calls `listArticles()`
 * → renders ArticleList + ArticleFilters.
 */

import Nav from "@/app/_components/nav";
import { listArticles } from "@/lib/api/articles";

import ArticleFilters from "./_components/article-filters";
import ArticleList from "./_components/article-list";

interface PageProps {
  searchParams: Promise<{
    category?: string;
    audience?: string;
    language?: string;
    tags?: string;
    cursor?: string;
    limit?: string;
  }>;
}

export default async function ArticlesPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const limit = params.limit ? Number(params.limit) : undefined;

  const response = await listArticles({
    category: params.category,
    audience: params.audience,
    language: params.language,
    tags: params.tags,
    cursor: params.cursor,
    limit: typeof limit === "number" && !Number.isNaN(limit) ? limit : undefined,
  });

  // currentParamsString — все фильтры БЕЗ cursor (для "next page" link).
  const queryWithoutCursor = new URLSearchParams();
  if (params.category) queryWithoutCursor.set("category", params.category);
  if (params.audience) queryWithoutCursor.set("audience", params.audience);
  if (params.language) queryWithoutCursor.set("language", params.language);
  if (params.tags) queryWithoutCursor.set("tags", params.tags);

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Статьи</h1>
          <p className="mt-1 text-sm text-gray-600">
            База знаний reHome — справочник, политики, FAQ и инструкции.
          </p>
        </header>
        <ArticleFilters
          initial={{
            category: params.category ?? "",
            audience: params.audience ?? "",
            language: params.language ?? "",
            tags: params.tags ?? "",
          }}
        />
        <ArticleList
          data={response.data}
          pagination={response.pagination}
          currentParamsString={queryWithoutCursor.toString()}
        />
      </main>
    </>
  );
}
