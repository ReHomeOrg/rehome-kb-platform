/**
 * Document list (UI.5 #83) — Server Component, card grid + pagination.
 */

import Link from "next/link";

import type { DocumentMeta, PaginationInfo } from "@/lib/api/types";

interface DocumentListProps {
  data: DocumentMeta[];
  pagination: PaginationInfo;
  currentParamsString: string;
}

export default function DocumentList({
  data,
  pagination,
  currentParamsString,
}: DocumentListProps): JSX.Element {
  if (data.length === 0) {
    return (
      <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Документов не найдено.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {data.map((doc) => (
          <li
            key={doc.id}
            className="rounded-md border border-gray-200 p-4 hover:border-gray-400"
          >
            <Link
              href={`/documents/${doc.id}`}
              className="block text-base font-medium hover:underline"
            >
              {doc.title}
            </Link>
            <p className="mt-1 text-xs text-gray-500">
              Категория {doc.category} · {doc.status} · {doc.confidentiality}
            </p>
            {doc.version ? (
              <p className="mt-1 text-xs text-gray-500">
                Версия {doc.version}
              </p>
            ) : null}
            {doc.effective_from ? (
              <p className="mt-1 text-xs text-gray-500">
                Действует с {doc.effective_from}
                {doc.effective_to ? ` по ${doc.effective_to}` : ""}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
      {pagination.has_more && pagination.cursor_next ? (
        <nav className="flex justify-end">
          <Link
            href={
              "/documents?" +
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
