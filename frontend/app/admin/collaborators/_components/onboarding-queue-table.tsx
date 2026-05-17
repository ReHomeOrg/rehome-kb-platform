/**
 * Onboarding queue table (#192).
 *
 * Server Component — renders компактный список PENDING_REVIEW
 * коллаборантов с inline lifecycle-actions (LifecycleActions —
 * client component, hydrated отдельно).
 */

import Link from "next/link";

import type {
  CollaboratorInternal,
  CollaboratorPublic,
} from "@/lib/api/types";

import LifecycleActions from "./lifecycle-actions";

interface Props {
  data: Array<CollaboratorPublic | CollaboratorInternal>;
}

const SOURCE_LABELS: Record<string, string> = {
  form: "Публичная форма",
  staff_invite: "Staff-invited",
  api: "API import",
  migration: "Migration",
};

function isInternal(
  c: CollaboratorPublic | CollaboratorInternal,
): c is CollaboratorInternal {
  return "name" in c;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function OnboardingQueueTable({ data }: Props): JSX.Element {
  if (data.length === 0) {
    return (
      <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Очередь пуста — нет коллаборантов в статусе PENDING_REVIEW. Когда
        кто-то заполнит публичную форму онбординга, заявка появится здесь.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-left text-xs uppercase text-gray-500">
            <th className="px-3 py-2 font-medium">Заявка</th>
            <th className="px-3 py-2 font-medium">Источник</th>
            <th className="px-3 py-2 font-medium">География</th>
            <th className="px-3 py-2 font-medium">Создан</th>
            <th className="px-3 py-2 font-medium">Действия</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {data.map((c) => {
            const internal = isInternal(c) ? c : null;
            const sourceKey = internal?.onboarding_source ?? null;
            return (
              <tr key={c.id} className="hover:bg-gray-50">
                <td className="px-3 py-2">
                  <Link
                    href={`/admin/collaborators/${encodeURIComponent(c.id)}`}
                    className="font-medium text-gray-900 hover:underline"
                  >
                    {internal?.name ?? c.brand_name ?? c.id.slice(0, 8)}
                  </Link>
                  <div className="text-xs text-gray-500">
                    {c.type} · группа {c.financial_group}
                  </div>
                </td>
                <td className="px-3 py-2 text-xs text-gray-700">
                  {sourceKey ? (SOURCE_LABELS[sourceKey] ?? sourceKey) : "—"}
                </td>
                <td className="px-3 py-2 text-xs text-gray-700">
                  {c.service_area}
                </td>
                <td className="px-3 py-2 text-xs text-gray-700">
                  {internal ? formatDate(internal.created_at) : "—"}
                </td>
                <td className="px-3 py-2">
                  <LifecycleActions id={c.id} status={c.status} compact />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
