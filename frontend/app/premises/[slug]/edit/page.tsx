/**
 * /premises/[slug]/edit — partial update premises card (#162, staff_admin).
 *
 * Fetches current state SSR (для pre-fill form'ы) → renders client
 * component с initial values. 401 → /login; 403/404 → /premises.
 */

import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { getPremisesCard } from "@/lib/api/premises";

import PremisesForm from "../../_components/premises-form";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export default async function EditPremisesPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { slug } = await params;
  let card;
  try {
    card = await getPremisesCard(slug);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      redirect("/login");
    }
    if (err instanceof ApiError && err.status === 403) {
      redirect("/premises");
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
          href={`/premises/${slug}`}
          className="text-sm text-gray-600 hover:underline"
        >
          ← К карточке
        </Link>
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">
            Редактирование: {card.address}
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Slug неизменяем. Backend audit&apos;ит изменения с trace полей.
          </p>
        </header>
        <PremisesForm initial={card} />
      </main>
    </>
  );
}
