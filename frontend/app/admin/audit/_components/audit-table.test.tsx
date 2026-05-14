import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AuditRecord } from "@/lib/api/types";

import AuditTable from "./audit-table";

function _rec(over: Partial<AuditRecord> = {}): AuditRecord {
  return {
    id: "id-1",
    actor_sub: "user-abc-12345",
    action: "articles.created",
    resource_type: "article",
    resource_id: "test-slug",
    metadata: { access_level: "PUBLIC" },
    created_at: "2026-05-14T12:00:00Z",
    ...over,
  };
}

describe("AuditTable", () => {
  it("empty list → 'Записей не найдено'", () => {
    render(<AuditTable data={[]} />);
    expect(screen.getByText(/не найдено/i)).toBeInTheDocument();
  });

  it("renders action label", () => {
    render(<AuditTable data={[_rec()]} />);
    expect(screen.getByText("articles.created")).toBeInTheDocument();
  });

  it("renders resource type + id", () => {
    render(<AuditTable data={[_rec({ resource_id: "abc-xyz" })]} />);
    expect(screen.getByText("article")).toBeInTheDocument();
    expect(screen.getByText("abc-xyz")).toBeInTheDocument();
  });

  it("missing resource_id renders без code crash'а", () => {
    render(<AuditTable data={[_rec({ resource_id: null })]} />);
    expect(screen.getByText("article")).toBeInTheDocument();
  });

  it("empty metadata renders '—'", () => {
    render(<AuditTable data={[_rec({ metadata: {} })]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("populated metadata renders JSON pre block", () => {
    render(<AuditTable data={[_rec({ metadata: { foo: "bar" } })]} />);
    expect(screen.getByText(/"foo": "bar"/)).toBeInTheDocument();
  });
});
