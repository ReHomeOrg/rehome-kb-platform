/**
 * /documents — список документов с фильтрами и cursor пагинацией.
 */

import Nav from "@/app/_components/nav";
import { listDocuments } from "@/lib/api/documents";
import type {
  DocumentCategory,
  DocumentStatus,
} from "@/lib/api/types";

import DocumentFilters from "./_components/document-filters";
import DocumentList from "./_components/document-list";

interface PageProps {
  searchParams: Promise<{
    category?: string;
    status?: string;
    related_entity?: string;
    cursor?: string;
    limit?: string;
  }>;
}

const VALID_CATEGORIES = ["A", "B", "C", "D", "E", "F"];
const VALID_STATUSES = ["DRAFT", "ACTIVE", "EXPIRED", "CANCELLED"];

export default async function DocumentsPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const limit = params.limit ? Number(params.limit) : undefined;

  // Defensive: backend отвергнет invalid через 422, но frontend сам
  // проверяет — `category` ∈ enum, `status` ∈ enum. Иначе передаём
  // undefined (без filter).
  const category =
    params.category && VALID_CATEGORIES.includes(params.category)
      ? (params.category as DocumentCategory)
      : undefined;
  const status =
    params.status && VALID_STATUSES.includes(params.status)
      ? (params.status as DocumentStatus)
      : undefined;

  const response = await listDocuments({
    category,
    status,
    related_entity: params.related_entity,
    cursor: params.cursor,
    limit:
      typeof limit === "number" && !Number.isNaN(limit) ? limit : undefined,
  });

  const queryWithoutCursor = new URLSearchParams();
  if (category) queryWithoutCursor.set("category", category);
  if (status) queryWithoutCursor.set("status", status);
  if (params.related_entity) {
    queryWithoutCursor.set("related_entity", params.related_entity);
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">Документы</h1>
          <p className="mt-1 text-sm text-gray-600">
            Договоры, регуляторы, шаблоны и внутренние документы.
          </p>
        </header>
        <DocumentFilters
          initial={{
            category: params.category ?? "",
            status: params.status ?? "",
            related_entity: params.related_entity ?? "",
          }}
        />
        <DocumentList
          data={response.data}
          pagination={response.pagination}
          currentParamsString={queryWithoutCursor.toString()}
        />
      </main>
    </>
  );
}
