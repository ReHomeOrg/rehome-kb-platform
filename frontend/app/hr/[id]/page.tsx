/**
 * /hr/[id] — employee detail (#153).
 *
 * Каждый просмотр аудитуется backend'ом (PZ §7). 403 → redirect /hr
 * с restricted notice. 404 → notFound page.
 */

import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { getEmployee } from "@/lib/api/hr";
import type { EmployeeStatus } from "@/lib/api/types";

interface PageProps {
  params: Promise<{ id: string }>;
}

const STATUS_LABEL: Record<EmployeeStatus, string> = {
  ACTIVE: "Активен",
  ON_LEAVE: "В отпуске",
  TERMINATED: "Уволен",
};

export default async function EmployeeDetailPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { id } = await params;
  let emp;
  try {
    emp = await getEmployee(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      redirect("/login");
    }
    if (err instanceof ApiError && err.status === 403) {
      redirect("/hr");
    }
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
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
      </main>
    </>
  );
}
