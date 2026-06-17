/**
 * /articles — статьи списком, сгруппированным по категориям, с нумерацией.
 *
 * Server Component. Reads URL search params → fetches ВСЕ статьи (с учётом
 * фильтров, листая cursor до конца) → renders ArticleCategoryList +
 * ArticleFilters.
 */

import Link from "next/link";

import Nav from "@/app/_components/nav";
import { listArticles } from "@/lib/api/articles";
import { listCategories } from "@/lib/api/categories";
import { getSessionAccess } from "@/lib/auth/access";
import type { ArticleSummary, Category } from "@/lib/api/types";

import ArticleFilters, {
  type CategoryOption,
} from "./_components/article-filters";
import ArticleCategoryList from "./_components/article-category-list";

/** Размер страницы при выборке всех статей; cap на число страниц. */
const FETCH_PAGE_SIZE = 100;
const MAX_PAGES = 50;

/**
 * Плоский список категорий для выпадающего фильтра. Значение опции — `slug`
 * (бэкенд фильтрует `Article.category == categories.slug`), подпись — `title`.
 */
function flattenCategories(categories: Category[]): CategoryOption[] {
  const out: CategoryOption[] = [];
  for (const cat of categories) {
    out.push({ slug: cat.slug, title: cat.title });
    if (cat.children.length > 0) {
      out.push(...flattenCategories(cat.children));
    }
  }
  return out.sort((a, b) => a.title.localeCompare(b.title, "ru"));
}

interface PageProps {
  searchParams: Promise<{
    category?: string;
    audience?: string;
    language?: string;
    tags?: string;
  }>;
}

export default async function ArticlesPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;

  const { isStaffAdmin } = await getSessionAccess();

  // Все статьи (с учётом фильтров) — для группировки по категориям. Листаем
  // cursor до конца; MAX_PAGES — backstop на аномально большую базу.
  const articles: ArticleSummary[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const response = await listArticles({
      category: params.category,
      audience: params.audience,
      language: params.language,
      tags: params.tags,
      cursor,
      limit: FETCH_PAGE_SIZE,
    });
    articles.push(...response.data);
    if (!response.pagination.has_more || !response.pagination.cursor_next) {
      break;
    }
    cursor = response.pagination.cursor_next;
  }

  // Категории (дерево) — для группировки и для выпадающего фильтра. Сбой не
  // должен ронять страницу — деградируем до пустого списка.
  let categoriesTree: Category[] = [];
  try {
    const categories = await listCategories();
    categoriesTree = categories.data;
  } catch {
    categoriesTree = [];
  }
  const categoryOptions = flattenCategories(categoriesTree);

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
              className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-hover"
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
        <ArticleCategoryList
          articles={articles}
          categories={categoriesTree}
          isStaffAdmin={isStaffAdmin}
        />
      </main>
    </>
  );
}
