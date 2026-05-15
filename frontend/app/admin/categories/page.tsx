/**
 * /admin/categories — дерево категорий с article_count (#186).
 *
 * Backend (`GET /api/v1/categories`) — public endpoint, scope filter на
 * storage level. Tree rendering вынесен в `CategoriesTree` (testable).
 * CRUD не поддерживается (категории seed'ятся через миграции).
 */

import Nav from "@/app/_components/nav";
import { listCategories } from "@/lib/api/categories";
import { ApiError } from "@/lib/api/client";

import CategoriesTree from "./_components/categories-tree";

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
        <CategoriesTree data={body.data} error={error} />
      </main>
    </>
  );
}
