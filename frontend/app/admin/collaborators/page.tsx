/**
 * /admin/collaborators — список коллаборантов для staff (ADR-0014, ТЗ §10).
 *
 * STAFF+ scope — гость видит только D-группу (управляющие компании,
 * аварийки); STAFF видит все группы (A/B/C/D). Filter form работает
 * как GET с query params. Cursor-paginated.
 */

import Link from "next/link";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import {
  listCollaborators,
  type ListCollaboratorsFilters,
} from "@/lib/api/collaborators";
import type {
  CollaboratorInternal,
  CollaboratorPublic,
  CollaboratorStatus,
  CollaboratorType,
} from "@/lib/api/types";

import CollaboratorsFilters from "./_components/collaborators-filters";
import CollaboratorsTable from "./_components/collaborators-table";

interface PageProps {
  searchParams: Promise<{
    type?: string;
    status?: string;
    service_area?: string;
    cursor?: string;
  }>;
}

const PAGE_SIZE = 25;

function parseType(s: string | undefined): CollaboratorType | undefined {
  const valid: CollaboratorType[] = [
    "management_company",
    "emergency_service",
    "repair_handyman",
    "cleaning",
    "moving",
    "key_delivery",
    "insurance",
    "payment_partner",
    "kyc_provider",
    "edo_provider",
    "sms_voice",
    "it_infrastructure",
    "legal_consultant",
    "other",
  ];
  return (valid as string[]).includes(s ?? "")
    ? (s as CollaboratorType)
    : undefined;
}

function parseStatus(s: string | undefined): CollaboratorStatus | undefined {
  const valid: CollaboratorStatus[] = [
    "DRAFT",
    "PENDING_REVIEW",
    "ACTIVE",
    "SUSPENDED",
    "ARCHIVED",
  ];
  return (valid as string[]).includes(s ?? "")
    ? (s as CollaboratorStatus)
    : undefined;
}

export default async function AdminCollaboratorsPage({
  searchParams,
}: PageProps): Promise<JSX.Element> {
  const params = await searchParams;
  const filters: ListCollaboratorsFilters = {
    type: parseType(params.type),
    status: parseStatus(params.status),
    service_area: params.service_area?.trim() || undefined,
    cursor: params.cursor,
    limit: PAGE_SIZE,
  };

  let data: Array<CollaboratorPublic | CollaboratorInternal> = [];
  let pagination: { cursor_next: string | null; has_more: boolean } = {
    cursor_next: null,
    has_more: false,
  };
  let error: string | null = null;
  try {
    const resp = await listCollaborators(filters);
    data = resp.data;
    pagination = resp.pagination;
  } catch (err) {
    if (err instanceof ApiError) {
      error = `${err.status}: ${err.message}`;
    } else {
      error = err instanceof Error ? err.message : "Ошибка загрузки";
    }
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-8">
        <header className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">
            Коллаборанты
          </h1>
          <div className="flex items-center gap-2">
            <Link
              href="/admin/collaborators/onboarding"
              className="rounded-md border border-yellow-300 bg-yellow-50 px-3 py-1.5 text-sm font-medium text-yellow-800 hover:bg-yellow-100"
            >
              Очередь онбординга
            </Link>
            <Link
              href="/admin/collaborators/new"
              className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-hover"
            >
              + Создать
            </Link>
          </div>
        </header>

        <p className="text-xs text-gray-600">
          Внешние исполнители платформы (УК, аварийки, клининг, переезды,
          ремонт, страховые и т.д. — ТЗ §10). Видимость зависит от scope: гости
          и tenants видят только публичные контакты (группа D).
        </p>

        <CollaboratorsFilters initial={filters} />

        {error ? (
          <p
            role="alert"
            className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            {error}
          </p>
        ) : (
          <CollaboratorsTable data={data} />
        )}

        {pagination.cursor_next ? (
          <Link
            href={`/admin/collaborators?cursor=${encodeURIComponent(pagination.cursor_next)}`}
            className="self-start rounded-md border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            Следующая страница →
          </Link>
        ) : null}
      </main>
    </>
  );
}
