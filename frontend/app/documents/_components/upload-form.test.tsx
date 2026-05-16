import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import UploadForm from "./upload-form";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

const fetchMock = vi.fn();
const originalWindow = (globalThis as { window?: unknown }).window;

beforeEach(() => {
  (globalThis as { window?: unknown }).window = window;
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  fetchMock.mockReset();
  refreshMock.mockReset();
});

afterEach(() => {
  (globalThis as { window?: unknown }).window = originalWindow;
});

function pickFile(name = "doc.pdf", body = "hello"): File {
  return new File([body], name, { type: "application/pdf" });
}

function fillForm(file: File, version = "1.0"): void {
  const input = screen.getByLabelText(/Файл/) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
  const versionInput = screen.getByLabelText(/Версия/);
  fireEvent.change(versionInput, { target: { value: version } });
}

describe("UploadForm", () => {
  it("renders все обязательные поля", () => {
    render(<UploadForm documentId="doc-1" />);
    expect(screen.getByLabelText(/Файл/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Формат/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Версия/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Загрузить/ })).toBeInTheDocument();
  });

  it("auto-derive'ит формат из расширения файла", () => {
    render(<UploadForm documentId="doc-1" />);
    fireEvent.change(screen.getByLabelText(/Файл/), {
      target: { files: [pickFile("contract.docx")] },
    });
    const select = screen.getByLabelText(/Формат/) as HTMLSelectElement;
    expect(select.value).toBe("docx");
  });

  it("blocks submit без file и показывает ошибку", async () => {
    render(<UploadForm documentId="doc-1" />);
    fireEvent.click(screen.getByRole("button", { name: /Загрузить/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Выберите файл/);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("blocks submit без версии и показывает ошибку", async () => {
    render(<UploadForm documentId="doc-1" />);
    fireEvent.change(screen.getByLabelText(/Файл/), {
      target: { files: [pickFile()] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Загрузить/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/версию/);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("on success показывает status banner + refresh()", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          format: "pdf",
          version: "1.0",
          size_bytes: 5120,
          sha256: "abc",
          storage_key: "legal/external/doc-1/1.0/pdf.pdf",
        }),
        { status: 201 },
      ),
    );
    render(<UploadForm documentId="doc-1" />);
    fillForm(pickFile());
    fireEvent.click(screen.getByRole("button", { name: /Загрузить/ }));

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/Файл загружен/);
      expect(refreshMock).toHaveBeenCalledOnce();
    });

    const call = fetchMock.mock.calls[0];
    expect(call[0]).toBe("/api/kb/api/v1/documents/doc-1/files");
    expect(call[1]?.method).toBe("POST");
    const body = call[1]?.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("format")).toBe("pdf");
    expect(body.get("version")).toBe("1.0");
    expect(body.get("file")).toBeInstanceOf(File);
  });

  it("показывает 413 как «лимит 50 МБ»", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "too big" }), { status: 413 }),
    );
    render(<UploadForm documentId="doc-1" />);
    fillForm(pickFile());
    fireEvent.click(screen.getByRole("button", { name: /Загрузить/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/50 МБ/);
    });
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("показывает 403 как «только staff»", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "forbidden" }), { status: 403 }),
    );
    render(<UploadForm documentId="doc-1" />);
    fillForm(pickFile());
    fireEvent.click(screen.getByRole("button", { name: /Загрузить/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/staff/);
    });
  });

  it("показывает 503 как «хранилище недоступно»", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "no minio" }), { status: 503 }),
    );
    render(<UploadForm documentId="doc-1" />);
    fillForm(pickFile());
    fireEvent.click(screen.getByRole("button", { name: /Загрузить/ }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Хранилище/);
    });
  });

  it("encode'ит documentId в URL", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          format: "pdf",
          version: "1.0",
          size_bytes: 1,
          sha256: "x",
          storage_key: "k",
        }),
        { status: 201 },
      ),
    );
    render(<UploadForm documentId="abc/with space" />);
    fillForm(pickFile());
    fireEvent.click(screen.getByRole("button", { name: /Загрузить/ }));
    await waitFor(() => {
      expect(fetchMock.mock.calls[0][0]).toBe(
        "/api/kb/api/v1/documents/abc%2Fwith%20space/files",
      );
    });
  });
});
