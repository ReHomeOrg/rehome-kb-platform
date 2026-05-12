/**
 * Documents API methods (UI.1 #75) — typed wrappers.
 *
 * Maps to backend `/api/v1/documents` (E2.8 #56).
 * NB: `/files/{format}` endpoint возвращает 501 в этом эпике
 * (architect approved deferral до kb-files эпика).
 */

import { apiFetch } from "./client";
import type {
  Document,
  DocumentCategory,
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
