/**
 * /premises — каталог карточек квартир (#160, PZ §5).
 *
 * Anonymous access: identification subset (address, cadastral, status).
 * Authorized + STAFF: detail с PII / financial blocks через detail page.
 *
 * Search mode: query param `?q=...` triggers POST /search; иначе
 * cursor-paginated list через GET.
 */

import Link from "next/link";

import Nav from "@/app/_components/nav";
import { listPremises, searchPremises } from "@/lib/api/premises";
import { ApiError } from "@/lib/api/client";
import { getSessionAccess } from "@/lib/auth/access";
import type {
  PremisesSearchHit,
  PremisesSummary,
} from "@/lib/api/types";

import PremisesList from "./_components/premises-list";
import SearchForm from "./_components/search-form";

interface PageProps {
  searchParams: Promise<{
    q?: string;
    cursor?: string;
    limit?: string;
  }>;
}

function searchHitsToSummaries(hits: PremisesSearchHit[]): PremisesSummary[] {
  // SearchHit shape близок к Summary, но без updated_at — синтезируем
  // pseudo-value для table layout consistency (frontend-only field).
  return hits.map((h) => ({
    id: h.id,
    slug: h.slug,
    status: h.status,
    address: h.address,
    postal_code: h.postal_code,
    cadastral_number: h.cadastral_number,
    updated_at: "",
  }));
}

export default async function PremisesPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const { isLoggedIn } = await getSessionAccess();

  // Каталог квартир доступен только авторизованным — иначе показываем
  // приглашение войти и НЕ обращаемся к API (бэкенд тоже гейтит доступ).
  if (!isLoggedIn) {
    return (
      <>
        <Nav />
        <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
          <h1 className="text-2xl font-semibold tracking-tight">Квартиры</h1>
          <div className="rounded-md border border-gray-200 bg-gray-50 p-6 text-center">
            <p className="text-sm text-gray-700">
              Для просмотра, пожалуйста, авторизуйтесь
            </p>
            <Link
              href="/login"
              className="mt-4 inline-block rounded-md bg-brand px-4 py-1.5 text-sm font-medium text-ink hover:bg-brand-hover"
            >
              Войти
            </Link>
          </div>
        </main>
      </>
    );
  }

  const params = await searchParams;
  const query = (params.q ?? "").trim();
  const limit = params.limit ? Number(params.limit) : undefined;

  let data: PremisesSummary[] = [];
  let pagination: { cursor_next: string | null; has_more: boolean } = {
    cursor_next: null,
    has_more: false,
  };
  let mode: "list" | "search" = "list";
  let error: string | null = null;

  try {
    if (query) {
      mode = "search";
      const response = await searchPremises({
        q: query,
        limit:
          typeof limit === "number" && !Number.isNaN(limit) ? limit : undefined,
      });
      data = searchHitsToSummaries(response.data);
    } else {
      const response = await listPremises({
        cursor: params.cursor,
        limit:
          typeof limit === "number" && !Number.isNaN(limit) ? limit : undefined,
      });
      data = response.data;
      pagination = response.pagination;
    }
  } catch (err) {
    if (err instanceof ApiError) {
      error = `Ошибка ${err.status}`;
    } else {
      throw err;
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Квартиры</h1>
            <p className="mt-1 text-sm text-gray-600">
              Каталог сдаваемых квартир. Полная карточка с финансовыми и
              контактными данными — для сотрудников reHome.
            </p>
          </div>
          <Link
            href="/premises/new"
            className="shrink-0 rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-ink hover:bg-brand-hover"
          >
            + Новая карточка
          </Link>
        </header>
        <SearchForm initialQuery={query} />
        {mode === "search" ? (
          <div className="flex items-center justify-between text-xs text-gray-500">
            <p>
              Поиск по «{query}» — найдено: {data.length}
            </p>
            <Link
              href="/premises"
              className="text-blue-700 underline hover:text-blue-900"
            >
              Сбросить поиск
            </Link>
          </div>
        ) : null}
        {error ? (
          <p
            role="status"
            className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700"
          >
            {error}
          </p>
        ) : (
          <PremisesList data={data} pagination={pagination} />
        )}
      </main>
    </>
  );
}
