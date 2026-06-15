/**
 * /articles — список статей с фильтрами + cursor пагинацией.
 *
 * Server Component. Reads URL search params → calls `listArticles()`
 * → renders ArticleList + ArticleFilters.
 */

import Link from "next/link";

import Nav from "@/app/_components/nav";
import { listArticles } from "@/lib/api/articles";
import { listCategories } from "@/lib/api/categories";
import { getSessionAccess } from "@/lib/auth/access";
import type { Category } from "@/lib/api/types";

import ArticleFilters from "./_components/article-filters";
import ArticleList from "./_components/article-list";

/** Плоский список названий категорий (title) для выпадающего фильтра. */
function flattenCategoryTitles(categories: Category[]): string[] {
  const titles: string[] = [];
  for (const cat of categories) {
    titles.push(cat.title);
    if (cat.children.length > 0) {
      titles.push(...flattenCategoryTitles(cat.children));
    }
  }
  return Array.from(new Set(titles)).sort((a, b) => a.localeCompare(b, "ru"));
}

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

  const { isStaffAdmin } = await getSessionAccess();

  const response = await listArticles({
    category: params.category,
    audience: params.audience,
    language: params.language,
    tags: params.tags,
    cursor: params.cursor,
    limit: typeof limit === "number" && !Number.isNaN(limit) ? limit : undefined,
  });

  // Список категорий для выпадающего фильтра. Сбой не должен ронять
  // страницу — деградируем до пустого списка (фильтр останется без опций).
  let categoryOptions: string[] = [];
  try {
    const categories = await listCategories();
    categoryOptions = flattenCategoryTitles(categories.data);
  } catch {
    categoryOptions = [];
  }

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
        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Статьи</h1>
            <p className="mt-1 text-sm text-gray-600">
              База знаний reHome — справочник, политики, FAQ и инструкции.
            </p>
          </div>
          {isStaffAdmin ? (
            <Link
              href="/articles/new"
              className="rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800"
            >
              + Создать
            </Link>
          ) : null}
        </header>
        <ArticleFilters
          initial={{
            category: params.category ?? "",
            audience: params.audience ?? "",
            language: params.language ?? "",
            tags: params.tags ?? "",
          }}
          categories={categoryOptions}
          isStaffAdmin={isStaffAdmin}
        />
        <ArticleList
          data={response.data}
          pagination={response.pagination}
          currentParamsString={queryWithoutCursor.toString()}
          isStaffAdmin={isStaffAdmin}
        />
      </main>
    </>
  );
}
