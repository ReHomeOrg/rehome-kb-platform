/**
 * DownloadButton (#108, ADR-0012 Phase A) — рендерит `<a>` ссылку на
 * proxy endpoint `/api/kb/api/v1/documents/{id}/files/{format}`.
 *
 * Клик → full navigation → proxy форвардит 302 от backend на signed
 * MinIO URL (TTL 5 мин). Browser автоматически следует за redirect и
 * скачивает файл.
 *
 * Если у файла нет `storage_key` (legacy row) — кнопка отключена,
 * чтобы не пугать пользователя 404.
 */

import type { DocumentFile } from "@/lib/api/types";
import { documentFileDownloadHref } from "@/lib/api/documents";

interface DownloadButtonProps {
  documentId: string;
  file: DocumentFile;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function DownloadButton({
  documentId,
  file,
}: DownloadButtonProps): JSX.Element {
  const sizeLabel = formatBytes(file.size_bytes);
  const label = `Скачать ${file.format.toUpperCase()} (${sizeLabel})`;

  if (!file.storage_key) {
    return (
      <span
        className="inline-flex items-center rounded-md border border-gray-200 bg-gray-50 px-3 py-1 text-xs text-gray-400"
        aria-disabled="true"
        title="Файл не загружен в хранилище"
      >
        {label}
      </span>
    );
  }

  return (
    <a
      href={documentFileDownloadHref(documentId, file.format)}
      className="inline-flex items-center rounded-md border border-gray-300 px-3 py-1 text-xs hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
      // Без `download` атрибута: backend отдаёт 302 на cross-origin MinIO
      // URL, `download` work'ает только same-origin. Browser открывает
      // файл по Content-Disposition / Content-Type из MinIO.
      rel="nofollow"
    >
      {label}
    </a>
  );
}
