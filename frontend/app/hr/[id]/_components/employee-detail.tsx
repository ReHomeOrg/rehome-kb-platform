/**
 * EmployeeDetail — render-only компонент (#195).
 *
 * Extracted из hr/[id]/page.tsx для testability. Page осталась
 * async server component для fetch/auth handling.
 */

import Link from "next/link";

import type { EmployeeStatus, HrEmployee } from "@/lib/api/types";

const STATUS_LABEL: Record<EmployeeStatus, string> = {
  ACTIVE: "Активен",
  ON_LEAVE: "В отпуске",
  TERMINATED: "Уволен",
};

interface Props {
  employee: HrEmployee;
}

export default function EmployeeDetail({ employee: emp }: Props): JSX.Element {
  return (
    <>
      <Link href="/hr" className="text-sm text-gray-600 hover:underline">
        ← К списку сотрудников
      </Link>
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">
          {emp.full_name}
        </h1>
        <p className="mt-1 text-base text-gray-600">{emp.position}</p>
        <dl className="mt-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <div>
            <dt className="font-medium text-gray-700">Подразделение</dt>
            <dd className="text-gray-500">{emp.department ?? "—"}</dd>
          </div>
          <div>
            <dt className="font-medium text-gray-700">Принят</dt>
            <dd className="text-gray-500">
              {new Date(emp.hire_date).toLocaleDateString("ru-RU")}
            </dd>
          </div>
          <div>
            <dt className="font-medium text-gray-700">Статус</dt>
            <dd className="text-gray-500">
              {STATUS_LABEL[emp.status as EmployeeStatus] ?? emp.status}
            </dd>
          </div>
          {emp.termination_date ? (
            <div>
              <dt className="font-medium text-gray-700">Уволен</dt>
              <dd className="text-gray-500">
                {new Date(emp.termination_date).toLocaleDateString("ru-RU")}
              </dd>
            </div>
          ) : null}
          {emp.personnel_number ? (
            <div>
              <dt className="font-medium text-gray-700">Табельный №</dt>
              <dd className="text-gray-500">{emp.personnel_number}</dd>
            </div>
          ) : null}
        </dl>
      </header>

      {Object.keys(emp.contact_info).length > 0 ? (
        <section className="rounded-md border border-gray-200 p-4">
          <h2 className="text-sm font-medium text-gray-700">Контакты</h2>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
            {Object.entries(emp.contact_info).map(([key, value]) => (
              <div key={key}>
                <dt className="font-medium text-gray-700">{key}</dt>
                <dd className="text-gray-600">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      {Object.keys(emp.notes).length > 0 ? (
        <section className="rounded-md border border-yellow-200 bg-yellow-50 p-4">
          <h2 className="text-sm font-medium text-yellow-900">
            Внутренние заметки HR
          </h2>
          <dl className="mt-2 flex flex-col gap-1 text-sm text-yellow-800">
            {Object.entries(emp.notes).map(([key, value]) => (
              <div key={key}>
                <span className="font-medium">{key}: </span>
                <span>{String(value)}</span>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      <p className="text-xs text-gray-500">
        ФЗ-152: данный просмотр зафиксирован в журнале аудита.
      </p>
    </>
  );
}
