/**
 * /admin/tags — read-only список тегов с article_count (#186).
 *
 * Backend (`GET /api/v1/tags`) — public endpoint, scope filter на
 * storage level. Admin view добавляет q-search + table layout для
 * navigation. CRUD не поддерживается (теги derive из tags column в
 * articles).
 */

import Nav from "@/app/_components/nav";
import { listTags } from "@/lib/api/tags";
import { ApiError } from "@/lib/api/client";

interface PageProps {
  searchParams: Promise<{
    q?: string;
  }>;
}

const PAGE_LIMIT = 200;

export default async function TagsAdminPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const q = params.q?.trim() || undefined;

  let body;
  let error: string | null = null;
  try {
    body = await listTags({ q, limit: PAGE_LIMIT });
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
          <h1 className="text-2xl font-semibold tracking-tight">Tags</h1>
          <p className="mt-1 text-sm text-gray-600">
            Список тегов из опубликованных статей. Сортировка по убыванию
            счётчика, далее по имени. Read-only.
          </p>
        </header>
        <form
          method="get"
          action="/admin/tags"
          role="search"
          aria-label="Tag search"
          className="flex items-end gap-3 rounded-md border border-gray-200 bg-gray-50 p-3"
        >
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-gray-600">Поиск (substring)</span>
            <input
              type="search"
              name="q"
              defaultValue={params.q ?? ""}
              placeholder="напр. налог, договор"
              maxLength={200}
              aria-label="Filter tags by substring"
              className="w-64 rounded-md border border-gray-300 px-2 py-1 text-xs"
            />
          </label>
          <button
            type="submit"
            className="rounded-md bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
          >
            Применить
          </button>
          {q ? (
            <a
              href="/admin/tags"
              aria-label="Reset search"
              className="text-xs text-blue-700 underline hover:text-blue-900"
            >
              Сбросить
            </a>
          ) : null}
        </form>
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
            Тегов не найдено.
          </p>
        ) : (
          <table
            className="w-full table-auto border-collapse text-sm"
            aria-label="Tags list"
          >
            <caption className="sr-only">Tag name and article count</caption>
            <thead>
              <tr className="border-b border-gray-300 text-left uppercase text-xs text-gray-500">
                <th scope="col" className="py-2 pr-3">
                  Имя
                </th>
                <th scope="col" className="py-2 pr-3 text-right">
                  Статей
                </th>
              </tr>
            </thead>
            <tbody>
              {body.data.map((tag) => (
                <tr
                  key={tag.name}
                  className="border-b border-gray-100 align-top"
                >
                  <td className="py-2 pr-3 font-mono">{tag.name}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {tag.article_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </main>
    </>
  );
}
