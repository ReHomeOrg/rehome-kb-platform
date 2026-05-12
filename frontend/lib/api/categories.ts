/**
 * Categories API methods (UI.1 #75) — typed wrappers.
 *
 * Maps to backend `/api/v1/categories` (E2.7 #54).
 */

import { apiFetch } from "./client";
import type { CategoriesListResponse } from "./types";

export async function listCategories(): Promise<CategoriesListResponse> {
  return apiFetch<CategoriesListResponse>("/api/v1/categories");
}
