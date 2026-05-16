/**
 * Collaborators list table (#184).
 *
 * Server-Component-friendly — accepts data prop, renders table without
 * client-side JS. Per-row link на detail page для drill-down.
 */

import Link from "next/link";

import type {
  CollaboratorInternal,
  CollaboratorPublic,
} from "@/lib/api/types";

interface Props {
  data: Array<CollaboratorPublic | CollaboratorInternal>;
}

const STATUS_BADGE_CLASSES: Record<string, string> = {
  ACTIVE: "bg-green-100 text-green-800",
  DRAFT: "bg-gray-100 text-gray-700",
  PENDING_REVIEW: "bg-yellow-100 text-yellow-800",
  SUSPENDED: "bg-orange-100 text-orange-800",
  ARCHIVED: "bg-red-100 text-red-700",
};

const GROUP_LABELS: Record<string, string> = {
  A: "A — мы платим",
  B: "B — через нас",
  C: "C — реферальная",
  D: "D — контакт",
};

function isInternal(
  c: CollaboratorPublic | CollaboratorInternal,
): c is CollaboratorInternal {
  return "name" in c;
}

export default function CollaboratorsTable({ data }: Props): JSX.Element {
  if (data.length === 0) {
    return (
      <p className="text-sm text-gray-600">
        Коллаборанты не найдены. Попробуйте изменить фильтры или создайте
        нового.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-left text-xs uppercase text-gray-500">
            <th className="px-3 py-2 font-medium">Название / Тип</th>
            <th className="px-3 py-2 font-medium">Группа</th>
            <th className="px-3 py-2 font-medium">Статус</th>
            <th className="px-3 py-2 font-medium">География</th>
            <th className="px-3 py-2 font-medium">Рейтинг</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {data.map((c) => (
            <tr key={c.id} className="hover:bg-gray-50">
              <td className="px-3 py-2">
                <Link
                  href={`/admin/collaborators/${encodeURIComponent(c.id)}`}
                  className="font-medium text-gray-900 hover:underline"
                >
                  {isInternal(c) ? c.name : (c.brand_name ?? c.id.slice(0, 8))}
                </Link>
                <div className="text-xs text-gray-500">{c.type}</div>
              </td>
              <td className="px-3 py-2 text-xs text-gray-700">
                {GROUP_LABELS[c.financial_group] ?? c.financial_group}
              </td>
              <td className="px-3 py-2">
                <span
                  className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                    STATUS_BADGE_CLASSES[c.status] ?? "bg-gray-100 text-gray-700"
                  }`}
                >
                  {c.status}
                </span>
              </td>
              <td className="px-3 py-2 text-xs text-gray-700">
                {c.service_area}
              </td>
              <td className="px-3 py-2 text-xs text-gray-700">
                {c.rating !== null ? c.rating.toFixed(1) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
