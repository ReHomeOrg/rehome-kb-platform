"use client";

/**
 * Download button (UI.5 #83) — отображает 501-deferred banner вместо
 * actual download.
 *
 * Per architect approval (#56), backend endpoint
 * GET /documents/{id}/files/{format} возвращает 501 до kb-files эпика
 * (MinIO + signed URLs). Frontend показывает hint, не делает запрос.
 */

import { useState } from "react";

interface DownloadDisabledProps {
  format: string;
  sizeBytes: number;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function DownloadDisabled({
  format,
  sizeBytes,
}: DownloadDisabledProps): JSX.Element {
  const [revealed, setRevealed] = useState(false);
  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => setRevealed(true)}
        className="rounded-md border border-gray-300 px-3 py-1 text-xs hover:bg-gray-50"
      >
        Скачать {format.toUpperCase()} ({formatBytes(sizeBytes)})
      </button>
      {revealed ? (
        <p className="text-xs text-amber-700">
          Скачивание будет доступно после развёртывания kb-files (Issue #56).
        </p>
      ) : null}
    </div>
  );
}
