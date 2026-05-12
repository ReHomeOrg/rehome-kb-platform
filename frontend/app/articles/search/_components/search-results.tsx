/**
 * Server Component — рендерит результаты поиска c sanitized snippets.
 *
 * snippet от backend (`ts_headline`) содержит `<b>...</b>` подсветку —
 * pass'ится через DOMPurify (whitelist `<b>` only) перед
 * dangerouslySetInnerHTML.
 */

import { sanitizeSearchSnippet } from "@/lib/sanitize";
import type { SearchHit } from "@/lib/api/types";

interface SearchResultsProps {
  hits: SearchHit[];
}

/**
 * NB (backlog): backend `SearchHit` сейчас содержит UUID `id`, но не
 * `slug`. Наш detail page `/articles/[slug]` ожидает slug. Чтобы
 * добавить link на detail, нужно либо расширить backend SearchHit
 * (добавить slug), либо менять detail-роут принимать id. Пока
 * показываем результат без link'a — backlog issue для следующего sweep.
 */
export default function SearchResults({
  hits,
}: SearchResultsProps): JSX.Element {
  if (hits.length === 0) {
    return (
      <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Ничего не найдено.
      </p>
    );
  }

  return (
    <ul className="flex flex-col gap-3">
      {hits.map((hit) => (
        <li
          key={hit.id}
          className="rounded-md border border-gray-200 p-4"
        >
          <h2 className="text-base font-medium">{hit.title}</h2>
          <p className="mt-1 text-xs text-gray-500">
            score {hit.score.toFixed(3)}
          </p>
          {hit.snippet ? (
            <p
              className="mt-2 text-sm text-gray-700"
              dangerouslySetInnerHTML={{
                __html: sanitizeSearchSnippet(hit.snippet),
              }}
            />
          ) : null}
        </li>
      ))}
    </ul>
  );
}
