/**
 * /hr/[id] — employee detail (#153).
 *
 * Каждый просмотр аудитуется backend'ом (PZ §7). 403 → redirect /hr
 * с restricted notice. 404 → notFound page. Render-only logic
 * вынесена в EmployeeDetail для testability.
 */

import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { getEmployee } from "@/lib/api/hr";

import ArchiveButton from "../_components/archive-button";
import EmployeeDetail from "./_components/employee-detail";

interface PageProps {
  params: Promise<{ id: string }>;
}

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
        <div className="flex items-center justify-between">
          <Link href="/hr" className="text-sm text-gray-600 hover:underline">
            ← К списку
          </Link>
          <div className="flex items-center gap-2">
            <Link
              href={`/hr/${encodeURIComponent(emp.id)}/edit`}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-50"
            >
              Редактировать
            </Link>
            <ArchiveButton id={emp.id} />
          </div>
        </div>
        <EmployeeDetail employee={emp} />
      </main>
    </>
  );
}
