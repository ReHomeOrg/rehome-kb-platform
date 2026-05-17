/**
 * /hr/[id]/edit — edit employee card (#197, PZ §7.1).
 */

import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { getEmployee } from "@/lib/api/hr";

import EmployeeForm from "../../_components/employee-form";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function HrEmployeeEditPage({
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
        <Link
          href={`/hr/${encodeURIComponent(emp.id)}`}
          className="text-sm text-gray-600 hover:underline"
        >
          ← К карточке
        </Link>
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">
            {emp.full_name}
          </h1>
          <p className="mt-1 text-xs text-gray-500">
            Редактирование. Изменение полей журналируется в audit_log (ПЗ §7.4).
          </p>
        </header>
        <EmployeeForm initial={emp} />
      </main>
    </>
  );
}
