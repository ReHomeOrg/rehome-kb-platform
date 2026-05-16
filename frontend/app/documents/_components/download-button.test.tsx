import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DocumentFile } from "@/lib/api/types";

import DownloadButton from "./download-button";

function fileFixture(
  override: Partial<DocumentFile> = {},
): DocumentFile {
  return {
    format: "pdf",
    size_bytes: 2048,
    sha256: "abc",
    storage_key: "legal/external/d/1/pdf.pdf",
    ...override,
  };
}

describe("DownloadButton", () => {
  it("renders anchor с proxy href и label", () => {
    render(<DownloadButton documentId="doc-1" file={fileFixture()} />);
    const link = screen.getByRole("link", { name: /PDF/ });
    expect(link).toHaveAttribute(
      "href",
      "/api/kb/api/v1/documents/doc-1/files/pdf",
    );
    expect(link).toHaveTextContent(/2.0 KB/);
  });

  it("formats MB", () => {
    render(
      <DownloadButton
        documentId="doc-1"
        file={fileFixture({ size_bytes: 5 * 1024 * 1024 })}
      />,
    );
    expect(screen.getByRole("link")).toHaveTextContent(/5.0 MB/);
  });

  it("formats sub-KB байты", () => {
    render(
      <DownloadButton
        documentId="doc-1"
        file={fileFixture({ size_bytes: 500 })}
      />,
    );
    expect(screen.getByRole("link")).toHaveTextContent(/500 B/);
  });

  it("encode'ит спец-символы в documentId", () => {
    render(
      <DownloadButton
        documentId="abc/with space"
        file={fileFixture()}
      />,
    );
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute(
      "href",
      "/api/kb/api/v1/documents/abc%2Fwith%20space/files/pdf",
    );
  });

  it("disable'ит кнопку если storage_key отсутствует (legacy row)", () => {
    render(
      <DownloadButton
        documentId="doc-1"
        file={fileFixture({ storage_key: null })}
      />,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    const disabled = screen.getByText(/PDF/);
    expect(disabled).toHaveAttribute("aria-disabled", "true");
  });

  it("respect'ит format в URL", () => {
    render(
      <DownloadButton
        documentId="doc-1"
        file={fileFixture({ format: "docx" })}
      />,
    );
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/api/kb/api/v1/documents/doc-1/files/docx",
    );
  });
});
