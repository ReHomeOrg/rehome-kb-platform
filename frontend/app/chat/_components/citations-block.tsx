/**
 * CitationsBlock — отображает sources под assistant message (#138).
 *
 * Skeleton: list of articles linkable на `/articles/{slug}`. Chunk index
 * показан badge'ем — `chunk #N` (1-indexed для UX, backend хранит
 * 0-indexed; offset делается здесь).
 */

import Link from "next/link";

import type { Citation } from "@/lib/api/types";

interface CitationsBlockProps {
  citations: Citation[];
}

export default function CitationsBlock({
  citations,
}: CitationsBlockProps): JSX.Element | null {
  if (citations.length === 0) {
    return null;
  }
  return (
    <details className="mt-2 rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs">
      <summary className="cursor-pointer font-medium text-gray-700">
        Источники ({citations.length})
      </summary>
      <ol className="mt-2 flex list-decimal flex-col gap-1 pl-5 text-gray-600">
        {citations.map((c, idx) => (
          <li key={`${c.id}-${c.chunk_index}-${c.question_id ?? "art"}-${idx}`}>
            <Link
              href={c.url}
              className="text-blue-700 underline hover:text-blue-900"
            >
              {c.title}
            </Link>{" "}
            {c.type === "article_question" ? (
              <span className="text-gray-500">
                · ответ на вопрос пользователя
              </span>
            ) : (
              <span className="text-gray-500">
                · chunk #{c.chunk_index + 1}
              </span>
            )}
          </li>
        ))}
      </ol>
    </details>
  );
}
