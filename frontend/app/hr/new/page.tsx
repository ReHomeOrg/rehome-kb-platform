/**
 * /hr/new — create employee (#197, PZ §7.1).
 *
 * Server Component shell — реальная форма в EmployeeForm client component.
 * HR_RESTRICTED scope enforce'ится на backend'е (POST returns 403 → form
 * показывает error inline).
 */

import Link from "next/link";

import Nav from "@/app/_components/nav";

import EmployeeForm from "../_components/employee-form";

export default function HrNewEmployeePage(): JSX.Element {
  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <Link href="/hr" className="text-sm text-gray-600 hover:underline">
          ← К списку сотрудников
        </Link>
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">
            Новый сотрудник
          </h1>
          <p className="mt-1 text-xs text-gray-500">
            Stage 1: базовая карточка. Паспорт, ИНН, СНИЛС, банк. реквизиты —
            backlog (требуется кадровая шифровка ПДн).
          </p>
        </header>
        <EmployeeForm />
      </main>
    </>
  );
}
