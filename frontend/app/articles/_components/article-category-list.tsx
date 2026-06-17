/**
 * /articles — статьи списком, сгруппированным по категориям, с нумерацией.
 *
 * Server Component. Группирует статьи по `category` в порядке дерева
 * категорий; внутри каждой категории — нумерованный список (по алфавиту).
 * Заменяет плиточную раскладку (ArticleList).
 */

import Link from "next/link";

import type { ArticleSummary, Category } from "@/lib/api/types";

interface ArticleCategoryListProps {
  articles: ArticleSummary[];
  /** Категории (дерево) — задают порядок и заголовки групп. */
  categories: Category[];
  /** Аудиторию в списке показываем только админ-стаффу. */
  isStaffAdmin: boolean;
}

interface CategoryGroup {
  key: string;
  title: string;
  articles: ArticleSummary[];
}

/** Плоский список категорий с сохранением порядка обхода дерева. */
function flatten(categories: Category[]): { slug: string; title: string }[] {
  const out: { slug: string; title: string }[] = [];
  for (const cat of categories) {
    out.push({ slug: cat.slug, title: cat.title });
    if (cat.children.length > 0) {
      out.push(...flatten(cat.children));
    }
  }
  return out;
}

/**
 * Группирует статьи по категориям в порядке дерева. `article.category`
 * сопоставляется и со `slug`, и с `title` категории (на части стендов они
 * совпадают). Статьи без известной категории — в группу «Без категории»
 * в конце. Группы без статей не выводятся.
 */
function buildGroups(
  articles: ArticleSummary[],
  categories: Category[],
): CategoryGroup[] {
  const flat = flatten(categories);
  const titleByKey = new Map<string, string>();
  for (const cat of flat) {
    titleByKey.set(cat.slug, cat.title);
    titleByKey.set(cat.title, cat.title);
  }

  const groups = new Map<string, CategoryGroup>();
  for (const cat of flat) {
    if (!groups.has(cat.title)) {
      groups.set(cat.title, { key: cat.title, title: cat.title, articles: [] });
    }
  }
  const uncategorized: CategoryGroup = {
    key: "__uncategorized__",
    title: "Без категории",
    articles: [],
  };

  for (const article of articles) {
    const groupTitle = titleByKey.get(article.category);
    const group = groupTitle ? groups.get(groupTitle) : undefined;
    (group ?? uncategorized).articles.push(article);
  }

  const collator = new Intl.Collator("ru");
  const sortByTitle = (group: CategoryGroup): void => {
    group.articles.sort((a, b) => collator.compare(a.title, b.title));
  };

  const result: CategoryGroup[] = [];
  for (const group of Array.from(groups.values())) {
    if (group.articles.length === 0) continue;
    sortByTitle(group);
    result.push(group);
  }
  if (uncategorized.articles.length > 0) {
    sortByTitle(uncategorized);
    result.push(uncategorized);
  }
  return result;
}

export default function ArticleCategoryList({
  articles,
  categories,
  isStaffAdmin,
}: ArticleCategoryListProps): JSX.Element {
  if (articles.length === 0) {
    return (
      <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Ничего не найдено. Попробуйте изменить фильтры.
      </p>
    );
  }

  const groups = buildGroups(articles, categories);

  return (
    <div className="flex flex-col gap-8">
      {groups.map((group) => (
        <section key={group.key}>
          <h2 className="mb-2 flex items-baseline gap-2 border-b border-gray-200 pb-1 text-lg font-semibold tracking-tight">
            {group.title}
            <span className="text-sm font-normal text-gray-500">
              {group.articles.length}
            </span>
          </h2>
          <ol className="list-decimal space-y-1 pl-8 text-sm marker:text-gray-400">
            {group.articles.map((article) => (
              <li key={article.id}>
                <Link
                  href={`/articles/${article.slug}`}
                  className="font-medium hover:underline"
                >
                  {article.title}
                </Link>
                {isStaffAdmin ? (
                  <span className="text-gray-500"> · {article.audience}</span>
                ) : null}
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}
