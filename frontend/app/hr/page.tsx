/**
 * /hr — employee directory (#153, PZ §7).
 *
 * HR_RESTRICTED scope обязателен на backend'е — non-HR scope получает
 * 403; UI делает graceful display. Server Component — список загружается
 * через SSR с cookie attach (см. apiFetch SSR mode).
 */

import Link from "next/link";
import { redirect } from "next/navigation";

import Nav from "@/app/_components/nav";
import { listEmployees } from "@/lib/api/hr";
import { ApiError } from "@/lib/api/client";

import EmployeeList from "./_components/employee-list";

interface PageProps {
  searchParams: Promise<{
    cursor?: string;
    limit?: string;
    include_terminated?: string;
  }>;
}

export default async function HrPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const limit = params.limit ? Number(params.limit) : undefined;
  const includeTerminated = params.include_terminated === "true";

  let response;
  try {
    response = await listEmployees({
      cursor: params.cursor,
      limit:
        typeof limit === "number" && !Number.isNaN(limit) ? limit : undefined,
      include_terminated: includeTerminated,
    });
  } catch (err) {
    // 401 → redirect на login (server-side, через Next router).
    // 403 → render restricted view (UX'еr знает почему — non-HR scope).
    if (err instanceof ApiError && err.status === 401) {
      redirect("/login");
    }
    if (err instanceof ApiError && err.status === 403) {
      return (
        <>
          <Nav />
          <main className="mx-auto max-w-3xl px-6 py-8">
            <h1 className="text-2xl font-semibold tracking-tight">Кадры</h1>
            <p
              role="status"
              className="mt-4 rounded-md border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-800"
            >
              Доступ к разделу «Кадры» ограничен — требуется роль{" "}
              <code>staff_hr</code> или <code>director</code>.
            </p>
          </main>
        </>
      );
    }
    throw err;
  }

  const queryWithoutCursor = new URLSearchParams();
  if (includeTerminated) {
    queryWithoutCursor.set("include_terminated", "true");
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Кадры</h1>
            <p className="mt-1 text-sm text-gray-600">
              Карточки сотрудников. Все просмотры аудитуются.
            </p>
          </div>
          <Link
            href="/hr/new"
            className="rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-gray-800"
          >
            + Создать
          </Link>
        </header>
        <div className="flex items-center justify-between">
          <p className="text-xs text-gray-500">
            Найдено: {response.data.length}
            {response.pagination.has_more ? "+" : ""}
          </p>
          <Link
            href={includeTerminated ? "/hr" : "/hr?include_terminated=true"}
            className="text-sm text-blue-700 underline hover:text-blue-900"
          >
            {includeTerminated
              ? "Скрыть уволенных"
              : "Показать уволенных"}
          </Link>
        </div>
        <EmployeeList
          data={response.data}
          pagination={response.pagination}
          currentParamsString={queryWithoutCursor.toString()}
        />
      </main>
    </>
  );
}
