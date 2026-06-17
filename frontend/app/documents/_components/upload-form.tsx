"use client";

/**
 * Upload form для document file (ADR-0012 Phase B, #215, STAFF-only).
 *
 * Multipart POST → proxy → backend → MinIO. После 201:
 * - сообщение об успехе
 * - `router.refresh()` чтобы Server Component перерендерил с обновлённым
 *   `files` массивом
 *
 * Frontend НЕ gate'ит UI по роли — следуем pattern'у premises-form.tsx:
 * показываем всем, backend возвращает 403 для non-STAFF, мы ловим
 * ApiError(403) и показываем пользователю причину.
 */

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import {
  type UploadedDocumentFile,
  uploadDocumentFile,
} from "@/lib/api/documents";
import type { DocumentFileFormat } from "@/lib/api/types";

const FORMATS: readonly DocumentFileFormat[] = ["pdf", "docx", "html"] as const;

interface Props {
  documentId: string;
}

function deriveFormatFromName(name: string): DocumentFileFormat | null {
  const lower = name.toLowerCase();
  if (lower.endsWith(".pdf")) return "pdf";
  if (lower.endsWith(".docx")) return "docx";
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
  return null;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: unknown } | null;
    const detail = body && typeof body.detail === "string" ? body.detail : null;
    if (err.status === 413) {
      return "Файл превышает лимит 50 МБ.";
    }
    if (err.status === 403) {
      return "Загрузка доступна только staff-ролям.";
    }
    if (err.status === 503) {
      return "Хранилище недоступно — попробуйте позже.";
    }
    return detail ? `${err.status}: ${detail}` : `${err.status}: ${err.message}`;
  }
  return err instanceof Error ? err.message : "Ошибка загрузки";
}

export default function UploadForm({ documentId }: Props): JSX.Element {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState<DocumentFileFormat>("pdf");
  const [version, setVersion] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<UploadedDocumentFile | null>(null);

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>): void {
    const picked = e.target.files?.[0] ?? null;
    setFile(picked);
    if (picked) {
      const derived = deriveFormatFromName(picked.name);
      if (derived) setFormat(derived);
    }
  }

  async function onSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    if (!file) {
      setError("Выберите файл.");
      return;
    }
    if (!version.trim()) {
      setError("Укажите версию.");
      return;
    }
    setPending(true);
    try {
      const uploaded = await uploadDocumentFile(
        documentId,
        file,
        format,
        version.trim(),
      );
      setSuccess(uploaded);
      setFile(null);
      setVersion("");
      router.refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-3 rounded-md border border-gray-200 p-4"
      aria-label="Загрузка файла документа"
    >
      <h2 className="text-sm font-medium text-gray-700">Загрузить файл</h2>
      <p className="text-xs text-gray-500">
        Доступно для staff-ролей. Файл будет загружен в защищённое хранилище
        и привязан к этому документу.
      </p>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-gray-700">Файл</span>
        <input
          type="file"
          onChange={onFileChange}
          accept=".pdf,.docx,.html,.htm"
          className="text-sm"
        />
      </label>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Формат</span>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value as DocumentFileFormat)}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          >
            {FORMATS.map((f) => (
              <option key={f} value={f}>
                {f.toUpperCase()}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-gray-700">Версия</span>
          <input
            type="text"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            maxLength={50}
            placeholder="1.0"
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm"
          />
        </label>
      </div>

      {error ? (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-red-700"
        >
          {error}
        </p>
      ) : null}

      {success ? (
        <p
          role="status"
          className="rounded-md border border-green-200 bg-green-50 p-2 text-xs text-green-700"
        >
          Файл загружен: {success.format.toUpperCase()} ·{" "}
          {(success.size_bytes / 1024).toFixed(1)} KB · версия{" "}
          {success.version}
        </p>
      ) : null}

      <div>
        <button
          type="submit"
          disabled={pending}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-hover disabled:opacity-50"
        >
          {pending ? "Загружаем…" : "Загрузить"}
        </button>
      </div>
    </form>
  );
}
