/**
 * Server Component — рендерит карточки articles + пагинацию.
 */

import Link from "next/link";

import type { ArticleSummary, PaginationInfo } from "@/lib/api/types";

interface ArticleListProps {
  data: ArticleSummary[];
  pagination: PaginationInfo;
  currentParamsString: string; // URL query без cursor, для построения "next page" link
  /** Аудиторию в превью показываем только админ-стаффу. */
  isStaffAdmin: boolean;
}

export default function ArticleList({
  data,
  pagination,
  currentParamsString,
  isStaffAdmin,
}: ArticleListProps): JSX.Element {
  if (data.length === 0) {
    return (
      <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Ничего не найдено. Попробуйте изменить фильтры.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {data.map((article) => (
          <li
            key={article.id}
            className="rounded-md border border-gray-200 p-4 hover:border-gray-400"
          >
            <Link
              href={`/articles/${article.slug}`}
              className="block text-base font-medium hover:underline"
            >
              {article.title}
            </Link>
            <p className="mt-1 text-xs text-gray-500">
              {article.category}
              {isStaffAdmin ? ` · ${article.audience}` : ""} · {article.status}
            </p>
            {article.tags.length > 0 ? (
              <p className="mt-2 flex flex-wrap gap-1 text-xs">
                {article.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded bg-gray-100 px-1.5 py-0.5 text-gray-700"
                  >
                    {tag}
                  </span>
                ))}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
      {pagination.has_more && pagination.cursor_next ? (
        <nav className="flex justify-end">
          <Link
            href={
              "/articles?" +
              (currentParamsString ? currentParamsString + "&" : "") +
              `cursor=${encodeURIComponent(pagination.cursor_next)}`
            }
            className="rounded-md border border-gray-300 px-4 py-1.5 text-sm hover:bg-gray-50"
          >
            Следующая страница →
          </Link>
        </nav>
      ) : null}
    </div>
  );
}
