/**
 * /admin/categories — дерево категорий с article_count (#186).
 *
 * Backend (`GET /api/v1/categories`) — public endpoint, scope filter на
 * storage level. Hierarchy: parent → children, рендерим через
 * рекурсивный <ul>. CRUD не поддерживается (категории seed'ятся
 * через миграции).
 */

import Nav from "@/app/_components/nav";
import { listCategories } from "@/lib/api/categories";
import { ApiError } from "@/lib/api/client";
import type { Category } from "@/lib/api/types";

function CategoryNode({
  node,
  depth,
}: {
  node: Category;
  depth: number;
}): JSX.Element {
  return (
    <li className="text-sm">
      <div className="flex items-baseline gap-2 py-1">
        <span className="font-medium" style={{ paddingLeft: depth * 12 }}>
          {node.title}
        </span>
        <code
          className="text-[10px] text-gray-500"
          aria-label={`Slug ${node.slug}`}
        >
          {node.slug}
        </code>
        <span
          className="ml-auto tabular-nums text-xs text-gray-600"
          aria-label={`${node.article_count} articles`}
        >
          {node.article_count}
        </span>
      </div>
      {node.description ? (
        <p className="pl-3 pr-3 text-xs text-gray-500" style={{ paddingLeft: depth * 12 + 12 }}>
          {node.description}
        </p>
      ) : null}
      {node.children.length > 0 ? (
        <ul role="group" className="border-l border-gray-100">
          {node.children.map((child) => (
            <CategoryNode key={child.slug} node={child} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export default async function CategoriesAdminPage(): Promise<JSX.Element> {
  let body;
  let error: string | null = null;
  try {
    body = await listCategories();
  } catch (err) {
    if (err instanceof ApiError) {
      error =
        err.status === 401 ? "Требуется авторизация." : `Ошибка ${err.status}`;
      body = { data: [] };
    } else {
      throw err;
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Categories</h1>
          <p className="mt-1 text-sm text-gray-600">
            Дерево категорий статей. Сортировка на каждом уровне:
            article_count убывающее, slug возрастающее. Read-only.
          </p>
        </header>
        {error ? (
          <p
            role="status"
            className="rounded-md border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-800"
          >
            {error}
          </p>
        ) : body.data.length === 0 ? (
          <p
            role="status"
            className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600"
          >
            Категорий нет.
          </p>
        ) : (
          <ul
            role="tree"
            aria-label="Category tree"
            className="rounded-md border border-gray-200 bg-white p-2"
          >
            {body.data.map((node) => (
              <CategoryNode key={node.slug} node={node} depth={0} />
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
