/**
 * Documents API methods (UI.1 #75) — typed wrappers.
 *
 * Maps to backend `/api/v1/documents` (E2.8 #56).
 * Phase A (#214, ADR-0012): `/files/{format}` возвращает 302 на signed
 * MinIO URL. Frontend использует `documentFileDownloadHref` для
 * generation browser-side ссылки через proxy `/api/kb/...`.
 */

import { apiFetch } from "./client";
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
  return `/api/kb/api/v1/documents/${encodeURIComponent(documentId)}/files/${encodeURIComponent(format)}`;
}
