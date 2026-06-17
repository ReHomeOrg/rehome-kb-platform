/**
 * Documents API methods (UI.1 #75) — typed wrappers.
 *
 * Maps to backend `/api/v1/documents` (E2.8 #56).
 * Phase A (#214, ADR-0012): `/files/{format}` возвращает 302 на signed
 * MinIO URL. Frontend использует `documentFileDownloadHref` для
 * generation browser-side ссылки через proxy `/api/kb/...`.
 */

import { ApiError, apiFetch } from "./client";
import { BASE_PATH } from "@/lib/base-path";
import type {
  Document,
  DocumentCategory,
  DocumentFileFormat,
  DocumentsListResponse,
  DocumentStatus,
} from "./types";

export interface ListDocumentsFilters {
  category?: DocumentCategory;
  status?: DocumentStatus;
  related_entity?: string;
  cursor?: string;
  limit?: number;
}

export async function listDocuments(
  filters: ListDocumentsFilters = {},
): Promise<DocumentsListResponse> {
  const params = new URLSearchParams();
  if (filters.category) params.set("category", filters.category);
  if (filters.status) params.set("status", filters.status);
  if (filters.related_entity) params.set("related_entity", filters.related_entity);
  if (filters.cursor) params.set("cursor", filters.cursor);
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  const qs = params.toString();
  return apiFetch<DocumentsListResponse>(
    `/api/v1/documents${qs ? `?${qs}` : ""}`,
  );
}

export async function getDocument(id: string): Promise<Document> {
  return apiFetch<Document>(`/api/v1/documents/${encodeURIComponent(id)}`);
}

/**
 * Browser-side href для download endpoint'а — клик по `<a href>`
 * триггерит full navigation в proxy `/api/kb/...`, который форвардит
 * 302 от backend на signed MinIO URL.
 *
 * Используется только в client-компонентах. SSR не имеет смысла —
 * download происходит по клику пользователя.
 */
export function documentFileDownloadHref(
  documentId: string,
  format: DocumentFileFormat,
): string {
  const prefix = BASE_PATH;
  return `${prefix}/api/kb/api/v1/documents/${encodeURIComponent(documentId)}/files/${encodeURIComponent(format)}`;
}

export interface UploadedDocumentFile {
  format: DocumentFileFormat;
  version: string;
  size_bytes: number;
  sha256: string;
  storage_key: string;
}

/**
 * Multipart POST на `/api/v1/documents/{id}/files` (Phase B, #215, STAFF+).
 *
 * Используем `fetch()` напрямую (не `apiFetch`), потому что `apiFetch`
 * принудительно ставит `Content-Type: application/json` — для multipart
 * нужно дать браузеру выставить boundary самому.
 *
 * Browser-only: форма — client component, SSR upload бессмысленен.
 */
export async function uploadDocumentFile(
  documentId: string,
  file: File,
  format: DocumentFileFormat,
  version: string,
): Promise<UploadedDocumentFile> {
  const body = new FormData();
  body.append("file", file);
  body.append("format", format);
  body.append("version", version);

  const prefix = BASE_PATH;
  const url = `${prefix}/api/kb/api/v1/documents/${encodeURIComponent(documentId)}/files`;
  const response = await fetch(url, { method: "POST", body });
  if (!response.ok) {
    let parsedBody: unknown;
    try {
      parsedBody = await response.json();
    } catch {
      parsedBody = await response.text().catch(() => null);
    }
    throw new ApiError(response.status, parsedBody);
  }
  return (await response.json()) as UploadedDocumentFile;
}
