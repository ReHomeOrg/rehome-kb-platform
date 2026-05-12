import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DocumentMeta, PaginationInfo } from "@/lib/api/types";

import DocumentList from "./document-list";

const sample: DocumentMeta = {
  id: "11111111-1111-1111-1111-111111111111",
  title: "Договор найма СПБ-001",
  category: "B",
  version: "1.2",
  effective_from: "2026-01-01",
  effective_to: null,
  status: "ACTIVE",
  counterparty: "ООО Заказчик",
  confidentiality: "INTERNAL",
  related_entity: null,
  files: [],
};

const NO_MORE: PaginationInfo = { cursor_next: null, has_more: false };
const HAS_MORE: PaginationInfo = { cursor_next: "next123", has_more: true };

describe("DocumentList", () => {
  it("renders empty state", () => {
    render(
      <DocumentList data={[]} pagination={NO_MORE} currentParamsString="" />,
    );
    expect(screen.getByText(/Документов не найдено/)).toBeInTheDocument();
  });

  it("renders card with version + period", () => {
    render(
      <DocumentList
        data={[sample]}
        pagination={NO_MORE}
        currentParamsString=""
      />,
    );
    expect(screen.getByText(/Договор найма СПБ-001/)).toBeInTheDocument();
    expect(screen.getByText(/Версия 1.2/)).toBeInTheDocument();
    expect(screen.getByText(/Действует с 2026-01-01/)).toBeInTheDocument();
  });

  it("links to /documents/[id]", () => {
    render(
      <DocumentList
        data={[sample]}
        pagination={NO_MORE}
        currentParamsString=""
      />,
    );
    const link = screen.getByText("Договор найма СПБ-001").closest("a");
    expect(link?.getAttribute("href")).toBe(`/documents/${sample.id}`);
  });

  it("renders next page link with cursor", () => {
    render(
      <DocumentList
        data={[sample]}
        pagination={HAS_MORE}
        currentParamsString="category=B"
      />,
    );
    const next = screen.getByText(/Следующая страница/);
    expect(next.closest("a")?.getAttribute("href")).toContain("cursor=next123");
    expect(next.closest("a")?.getAttribute("href")).toContain("category=B");
  });

  it("omits next link when no_more", () => {
    render(
      <DocumentList
        data={[sample]}
        pagination={NO_MORE}
        currentParamsString=""
      />,
    );
    expect(screen.queryByText(/Следующая страница/)).not.toBeInTheDocument();
  });
});
