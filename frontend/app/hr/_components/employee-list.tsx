/**
 * Employee list table (#153).
 *
 * Server Component — read-only render of summaries. Per-row link
 * на detail page. ПДн (contact_info, notes) НЕ показывается —
 * security-by-design (summaries не содержат PII).
 */

import Link from "next/link";

import type {
  EmployeeStatus,
  HrEmployeeSummary,
} from "@/lib/api/types";

interface Props {
  data: HrEmployeeSummary[];
  pagination: { cursor_next: string | null; has_more: boolean };
  currentParamsString: string;
}

const STATUS_BADGE_CLASS: Record<EmployeeStatus, string> = {
  ACTIVE: "bg-emerald-50 text-emerald-700",
  ON_LEAVE: "bg-yellow-50 text-yellow-700",
  TERMINATED: "bg-gray-100 text-gray-600",
};

const STATUS_LABEL: Record<EmployeeStatus, string> = {
  ACTIVE: "Активен",
  ON_LEAVE: "В отпуске",
  TERMINATED: "Уволен",
};

export default function EmployeeList({
  data,
  pagination,
  currentParamsString,
}: Props): JSX.Element {
  if (data.length === 0) {
    return (
      <p
        role="status"
        className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600"
      >
        Сотрудники не найдены.
      </p>
    );
  }

  // Cursor-based pagination — next page href с сохранением filters.
  let nextHref: string | null = null;
  if (pagination.has_more && pagination.cursor_next) {
    const params = new URLSearchParams(currentParamsString);
    params.set("cursor", pagination.cursor_next);
    nextHref = `/hr?${params.toString()}`;
  }

  return (
    <div className="flex flex-col gap-4">
      <table
        className="w-full table-auto border-collapse text-sm"
        aria-label="Employee list"
      >
        <caption className="sr-only">
          ФИО, должность, подразделение, дата приёма, статус сотрудника
        </caption>
        <thead>
          <tr className="border-b border-gray-200 text-left text-xs uppercase text-gray-500">
            <th scope="col" className="py-2 pr-4">
              ФИО
            </th>
            <th scope="col" className="py-2 pr-4">
              Должность
            </th>
            <th scope="col" className="py-2 pr-4">
              Подразделение
            </th>
            <th scope="col" className="py-2 pr-4">
              Принят
            </th>
            <th scope="col" className="py-2 pr-4">
              Статус
            </th>
          </tr>
        </thead>
        <tbody>
          {data.map((e) => (
            <tr key={e.id} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="py-2 pr-4">
                <Link
                  href={`/hr/${e.id}`}
                  className="font-medium text-brand-strong hover:underline"
                >
                  {e.full_name}
                </Link>
              </td>
              <td className="py-2 pr-4 text-gray-700">{e.position}</td>
              <td className="py-2 pr-4 text-gray-600">{e.department ?? "—"}</td>
              <td className="py-2 pr-4 text-gray-500">
                {new Date(e.hire_date).toLocaleDateString("ru-RU")}
              </td>
              <td className="py-2 pr-4">
                <span
                  className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${
                    STATUS_BADGE_CLASS[e.status]
                  }`}
                >
                  {STATUS_LABEL[e.status]}
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
