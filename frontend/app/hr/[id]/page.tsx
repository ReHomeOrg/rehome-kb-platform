/**
 * /hr/[id] — employee detail (#153).
 *
 * Каждый просмотр аудитуется backend'ом (PZ §7). 403 → redirect /hr
 * с restricted notice. 404 → notFound page. Render-only logic
 * вынесена в EmployeeDetail для testability.
 */

import { notFound, redirect } from "next/navigation";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { getEmployee } from "@/lib/api/hr";

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
        <EmployeeDetail employee={emp} />
      </main>
    </>
  );
}
