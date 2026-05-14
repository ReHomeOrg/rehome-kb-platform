/**
 * Premises list table (#160).
 *
 * Server Component — identification subset only. STAFF tier видит
 * полную карточку через detail page (per-scope projection backend'ом).
 */

import Link from "next/link";

import type { PremisesStatus, PremisesSummary } from "@/lib/api/types";

interface Props {
  data: PremisesSummary[];
  pagination: { cursor_next: string | null; has_more: boolean };
}

const STATUS_BADGE: Record<string, string> = {
  DRAFT: "bg-gray-100 text-gray-700",
  PUBLISHED: "bg-emerald-50 text-emerald-700",
  RENTED: "bg-blue-50 text-blue-700",
  ARCHIVED: "bg-gray-100 text-gray-500",
};

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "Черновик",
  PUBLISHED: "Опубликована",
  RENTED: "Сдаётся",
  ARCHIVED: "Архив",
};

function statusBadgeClass(status: string): string {
  return STATUS_BADGE[status] ?? "bg-gray-100 text-gray-600";
}

function statusLabel(status: PremisesStatus | string): string {
  return STATUS_LABEL[status] ?? status;
}

export default function PremisesList({ data, pagination }: Props): JSX.Element {
  if (data.length === 0) {
    return (
      <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Карточки квартир не найдены.
      </p>
    );
  }

  let nextHref: string | null = null;
  if (pagination.has_more && pagination.cursor_next) {
    const params = new URLSearchParams();
    params.set("cursor", pagination.cursor_next);
    nextHref = `/premises?${params.toString()}`;
  }

  return (
    <div className="flex flex-col gap-4">
      <table className="w-full table-auto border-collapse text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-left text-xs uppercase text-gray-500">
            <th className="py-2 pr-4">Адрес</th>
            <th className="py-2 pr-4">Кадастровый №</th>
            <th className="py-2 pr-4">Индекс</th>
            <th className="py-2 pr-4">Статус</th>
          </tr>
        </thead>
        <tbody>
          {data.map((p) => (
            <tr key={p.id} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="py-2 pr-4">
                <Link
                  href={`/premises/${p.slug}`}
                  className="font-medium text-blue-700 hover:underline"
                >
                  {p.address}
                </Link>
              </td>
              <td className="py-2 pr-4 text-gray-600">
                {p.cadastral_number ?? "—"}
              </td>
              <td className="py-2 pr-4 text-gray-500">
                {p.postal_code ?? "—"}
              </td>
              <td className="py-2 pr-4">
                <span
                  className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${statusBadgeClass(p.status)}`}
                >
                  {statusLabel(p.status)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {nextHref ? (
        <Link
          href={nextHref}
          className="self-end rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
        >
          Следующая страница →
        </Link>
      ) : null}
    </div>
  );
}
