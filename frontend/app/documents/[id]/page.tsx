/**
 * /documents/[id] — detail (UI.5 #83).
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import Nav from "@/app/_components/nav";
import { ApiError } from "@/lib/api/client";
import { getDocument } from "@/lib/api/documents";

import DownloadDisabled from "../_components/download-disabled";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function DocumentDetailPage({
  params,
}: PageProps): Promise<JSX.Element> {
  const { id } = await params;
  let doc;
  try {
    doc = await getDocument(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  return (
    <>
      <Nav />
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-8">
        <Link href="/documents" className="text-sm text-gray-600 hover:underline">
          ← Назад к списку
        </Link>
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">
            {doc.title}
          </h1>
          <dl className="mt-4 grid grid-cols-2 gap-2 text-xs text-gray-500 sm:grid-cols-4">
            <div>
              <dt className="font-medium text-gray-700">Категория</dt>
              <dd>{doc.category}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-700">Статус</dt>
              <dd>{doc.status}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-700">Конфиденциальность</dt>
              <dd>{doc.confidentiality}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-700">Версия</dt>
              <dd>{doc.version ?? "—"}</dd>
            </div>
            {doc.counterparty ? (
              <div>
                <dt className="font-medium text-gray-700">Контрагент</dt>
                <dd>{doc.counterparty}</dd>
              </div>
            ) : null}
            {doc.related_entity ? (
              <div>
                <dt className="font-medium text-gray-700">Связь</dt>
                <dd>{doc.related_entity}</dd>
              </div>
            ) : null}
            {doc.effective_from ? (
              <div>
                <dt className="font-medium text-gray-700">Действует с</dt>
                <dd>{doc.effective_from}</dd>
              </div>
            ) : null}
            {doc.effective_to ? (
              <div>
                <dt className="font-medium text-gray-700">по</dt>
                <dd>{doc.effective_to}</dd>
              </div>
            ) : null}
          </dl>
        </header>

        {doc.files.length > 0 ? (
          <section className="rounded-md border border-gray-200 p-4">
            <h2 className="text-sm font-medium text-gray-700">Файлы</h2>
            <ul className="mt-2 flex flex-col gap-2">
              {doc.files.map((file) => (
                <li key={`${file.format}-${file.sha256}`}>
                  <DownloadDisabled
                    format={file.format}
                    sizeBytes={file.size_bytes}
                  />
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {doc.signed_by.length > 0 ? (
          <section className="rounded-md border border-gray-200 p-4">
            <h2 className="text-sm font-medium text-gray-700">Подписанты</h2>
            <ul className="mt-2 flex flex-col gap-1 text-sm">
              {doc.signed_by.map((s, idx) => (
                <li key={`${s.name}-${idx}`}>
                  <span className="font-medium">{s.name}</span> ({s.role}) ·{" "}
                  {new Date(s.date).toLocaleDateString("ru-RU")} · {s.method}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {doc.audit_log.length > 0 ? (
          <section className="rounded-md border border-gray-200 p-4">
            <h2 className="text-sm font-medium text-gray-700">Аудит-лог</h2>
            <ul className="mt-2 flex flex-col gap-1 text-xs text-gray-600">
              {doc.audit_log.map((entry, idx) => (
                <li key={`${entry.actor}-${idx}`}>
                  <code>{entry.actor}</code> — {entry.action} —{" "}
                  {new Date(entry.ts).toLocaleString("ru-RU")}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </main>
    </>
  );
}
