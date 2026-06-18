/**
 * /admin/security-incidents/[id] — incident detail + edit form (#255).
 *
 * GET /admin/security-incidents/{id} → form для resolve / status update.
 * PATCH endpoint (backend #231). staff_admin scope.
 */

import { notFound } from "next/navigation";

import Nav from "@/app/_components/nav";
import { getSecurityIncident } from "@/lib/api/admin-security-incidents";
import { ApiError } from "@/lib/api/client";
import type { SecurityIncident } from "@/lib/api/types";

import IncidentEditForm from "../_components/incident-edit-form";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function SecurityIncidentDetailPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { id } = await params;

  let incident: SecurityIncident | undefined;
  let error: string | undefined;
  try {
    incident = await getSecurityIncident(id);
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
      error = "Не удалось загрузить инцидент.";
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto max-w-3xl px-4 py-6">
        <a
          href="/admin/security-incidents"
          className="mb-3 inline-block text-xs text-brand-strong underline hover:text-ink"
        >
          ← Назад к списку
        </a>
        <h1 className="mb-4 text-2xl font-semibold">Security incident</h1>

        {error !== undefined ? (
          <div
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900"
          >
            {error}
          </div>
        ) : null}

        {incident ? <IncidentEditForm initial={incident} /> : null}
      </main>
    </>
  );
}
