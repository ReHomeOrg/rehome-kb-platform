/**
 * /premises/new — create premises card (#162, staff_admin).
 *
 * Server Component shell — реальный form в client component
 * (`PremisesForm`).
 */

import Link from "next/link";

import Nav from "@/app/_components/nav";

import PremisesForm from "../_components/premises-form";

export default function NewPremisesPage(): JSX.Element {
  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <Link
          href="/premises"
          className="text-sm text-gray-600 hover:underline"
        >
          ← К списку квартир
        </Link>
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">
            Новая карточка квартиры
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Создание требует роли staff_admin. Backend audit&apos;ит каждое
            создание.
          </p>
        </header>
        <PremisesForm />
      </main>
    </>
  );
}
