import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DownloadDisabled from "./download-disabled";

describe("DownloadDisabled", () => {
  it("renders button with format and size", () => {
    render(<DownloadDisabled format="pdf" sizeBytes={2048} />);
    expect(screen.getByText(/PDF/)).toBeInTheDocument();
    expect(screen.getByText(/2.0 KB/)).toBeInTheDocument();
  });

  it("shows kb-files hint on click", () => {
    render(<DownloadDisabled format="docx" sizeBytes={500} />);
    expect(
      screen.queryByText(/будет доступно/),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByText(/DOCX/));
    expect(screen.getByText(/kb-files/)).toBeInTheDocument();
  });

  it("formats bytes for MB", () => {
    render(<DownloadDisabled format="pdf" sizeBytes={5 * 1024 * 1024} />);
    expect(screen.getByText(/5.0 MB/)).toBeInTheDocument();
  });

  it("formats small bytes", () => {
    render(<DownloadDisabled format="pdf" sizeBytes={500} />);
    expect(screen.getByText(/500 B/)).toBeInTheDocument();
  });
});
