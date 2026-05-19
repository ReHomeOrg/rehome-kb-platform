/**
 * /admin/personal-data/[id] — PD request detail + process form (#256).
 *
 * ФЗ-152 §15 SAR processing workflow. staff_admin scope.
 */

import { notFound } from "next/navigation";

import Nav from "@/app/_components/nav";
import { getPdRequest } from "@/lib/api/admin-pd-requests";
import { ApiError } from "@/lib/api/client";
import type { PersonalDataRequest } from "@/lib/api/types";

import PdRequestProcessForm from "../_components/pd-request-process-form";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function PdRequestDetailPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { id } = await params;

  let request: PersonalDataRequest | undefined;
  let error: string | undefined;
  try {
    request = await getPdRequest(id);
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 404) {
        notFound();
      }
      if (e.status === 401 || e.status === 403) {
        error = "Доступ только для staff_admin.";
      } else {
        error = `Ошибка ${e.status}: ${e.message}`;
      }
    } else {
      error = "Не удалось загрузить заявку.";
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-3xl px-4 py-6">
        <a
          href="/admin/personal-data"
          className="mb-3 inline-block text-xs text-blue-700 underline hover:text-blue-900"
        >
          ← Назад к списку
        </a>
        <h1 className="mb-4 text-2xl font-semibold">SAR (ФЗ-152 §15)</h1>

        {error !== undefined ? (
          <div
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900"
          >
            {error}
          </div>
        ) : null}

        {request ? <PdRequestProcessForm initial={request} /> : null}
      </main>
    </>
  );
}
