/**
 * TagsList — render-only table component (#188).
 *
 * Extracted из page.tsx чтобы tests могли render'ить без async data
 * fetching. Page passes data | error state.
 */

import type { Tag } from "@/lib/api/types";

interface Props {
  data: Tag[];
  error: string | null;
}

export default function TagsList({ data, error }: Props): JSX.Element {
  if (error) {
    return (
      <p
        role="status"
        className="rounded-md border border-yellow-200 bg-yellow-50 p-4 text-sm text-yellow-800"
      >
        {error}
      </p>
    );
  }
  if (data.length === 0) {
    return (
      <p
        role="status"
        className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600"
      >
        Тегов не найдено.
      </p>
    );
  }
  return (
    <table
      className="w-full table-auto border-collapse text-sm"
      aria-label="Tags list"
    >
      <caption className="sr-only">Tag name and article count</caption>
      <thead>
        <tr className="border-b border-gray-300 text-left uppercase text-xs text-gray-500">
          <th scope="col" className="py-2 pr-3">
            Имя
          </th>
          <th scope="col" className="py-2 pr-3 text-right">
            Статей
          </th>
        </tr>
      </thead>
      <tbody>
        {data.map((tag) => (
          <tr key={tag.name} className="border-b border-gray-100 align-top">
            <td className="py-2 pr-3 font-mono">{tag.name}</td>
            <td className="py-2 pr-3 text-right tabular-nums">
              {tag.article_count}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
