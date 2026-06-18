/**
 * /premises/[slug] — detail premises card (#160).
 *
 * Per-scope projection backend'ом: anon видит только identification,
 * STAFF — все blocks (owner / financial / tenant_info / internal_data).
 * Frontend рендерит conditionally на presence полей.
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { getPremisesCard } from "@/lib/api/premises";
import type { PremisesStatus, PremisesView } from "@/lib/api/types";

import CollaboratorsSection from "./_components/collaborators-section";

interface PageProps {
  params: Promise<{ slug: string }>;
}

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "Черновик",
  PUBLISHED: "Опубликована",
  RENTED: "Сдаётся",
  ARCHIVED: "Архив",
};

function statusLabel(status: PremisesStatus | string): string {
  return STATUS_LABEL[status] ?? status;
}

function hasStaffBlocks(p: PremisesView): boolean {
  // Если хотя бы один STAFF-only block populated — caller — STAFF tier.
  return Boolean(
    p.owner ||
      p.current_tenant ||
      p.financial_data ||
      p.tenant_info ||
      p.internal_data,
  );
}

export default async function PremisesDetailPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { slug } = await params;
  let card: PremisesView;
  try {
    card = await getPremisesCard(slug);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  const isStaff = hasStaffBlocks(card);
  const extra = card.extra_identification ?? {};

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
          <div className="flex items-start justify-between gap-4">
            <h1 className="text-3xl font-semibold tracking-tight">
              {card.address}
            </h1>
            {isStaff ? (
              <Link
                href={`/premises/${card.slug}/edit`}
                className="shrink-0 rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
              >
                ✎ Редактировать
              </Link>
            ) : null}
          </div>
          <dl className="mt-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <div>
              <dt className="font-medium text-gray-700">Статус</dt>
              <dd className="text-gray-500">{statusLabel(card.status)}</dd>
            </div>
            {card.postal_code ? (
              <div>
                <dt className="font-medium text-gray-700">Индекс</dt>
                <dd className="text-gray-500">{card.postal_code}</dd>
              </div>
            ) : null}
            {card.cadastral_number ? (
              <div>
                <dt className="font-medium text-gray-700">Кадастровый №</dt>
                <dd className="text-gray-500">{card.cadastral_number}</dd>
              </div>
            ) : null}
            {card.internal_code ? (
              <div>
                <dt className="font-medium text-gray-700">Внутр. код</dt>
                <dd className="text-gray-500">{card.internal_code}</dd>
              </div>
            ) : null}
          </dl>
        </header>

        {Object.keys(extra).length > 0 ? (
          <section className="rounded-md border border-gray-200 p-4">
            <h2 className="text-sm font-medium text-gray-700">
              Идентификация
            </h2>
            <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
              {Object.entries(extra).map(([k, v]) => (
                <div key={k}>
                  <dt className="font-medium text-gray-700">{k}</dt>
                  <dd className="text-gray-600">{String(v)}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}

        <CollaboratorsSection premisesId={card.id} canManage={isStaff} />

        {isStaff ? (
          <>
            {card.owner && Object.keys(card.owner).length > 0 ? (
              <section className="rounded-md border border-gray-200 bg-amber-50 p-4">
                <h2 className="text-sm font-medium text-amber-900">
                  Собственник (только для сотрудников)
                </h2>
                <dl className="mt-2 grid grid-cols-2 gap-2 text-sm text-amber-900">
                  {Object.entries(card.owner).map(([k, v]) => (
                    <div key={k}>
                      <dt className="font-medium">{k}</dt>
                      <dd>{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ) : null}

            {card.current_tenant &&
            Object.keys(card.current_tenant).length > 0 ? (
              <section className="rounded-md border border-gray-200 bg-amber-50 p-4">
                <h2 className="text-sm font-medium text-amber-900">
                  Текущий наниматель
                </h2>
                <dl className="mt-2 grid grid-cols-2 gap-2 text-sm text-amber-900">
                  {Object.entries(card.current_tenant).map(([k, v]) => (
                    <div key={k}>
                      <dt className="font-medium">{k}</dt>
                      <dd>{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ) : null}

            {card.financial_data &&
            Object.keys(card.financial_data).length > 0 ? (
              <section className="rounded-md border border-mint bg-mint-soft p-4">
                <h2 className="text-sm font-medium text-ink">
                  Финансовая информация
                </h2>
                <dl className="mt-2 grid grid-cols-2 gap-2 text-sm text-ink">
                  {Object.entries(card.financial_data).map(([k, v]) => (
                    <div key={k}>
                      <dt className="font-medium">{k}</dt>
                      <dd>{String(v)}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            ) : null}

            {card.tenant_info && Object.keys(card.tenant_info).length > 0 ? (
              <section className="rounded-md border border-gray-200 p-4">
                <h2 className="text-sm font-medium text-gray-700">
                  Информация для жильца
                </h2>
                <pre className="mt-2 overflow-x-auto rounded bg-gray-50 p-2 text-xs">
                  {JSON.stringify(card.tenant_info, null, 2)}
                </pre>
              </section>
            ) : null}

            {card.internal_data &&
            Object.keys(card.internal_data).length > 0 ? (
              <section className="rounded-md border border-red-200 bg-red-50 p-4">
                <h2 className="text-sm font-medium text-red-900">
                  Внутренние данные (STAFF)
                </h2>
                <pre className="mt-2 overflow-x-auto rounded bg-red-100 p-2 text-xs text-red-900">
                  {JSON.stringify(card.internal_data, null, 2)}
                </pre>
              </section>
            ) : null}
          </>
        ) : (
          <p className="rounded-md border border-yellow-200 bg-yellow-50 p-4 text-xs text-yellow-800">
            Дополнительные сведения о собственнике, финансах и условиях аренды
            доступны сотрудникам reHome после входа в систему.
          </p>
        )}
      </main>
    </>
  );
}
