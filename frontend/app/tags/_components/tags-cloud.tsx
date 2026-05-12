/**
 * Tag cloud (UI.3 #79) — Server Component.
 *
 * Sizing: дискретные badge sizes по quartiles article_count
 * (xs/sm/md/lg). Sort из backend: article_count DESC, name ASC.
 *
 * Каждый tag — link на `/articles?tags=<name>`.
 */

import Link from "next/link";

import type { Tag } from "@/lib/api/types";

interface TagsCloudProps {
  tags: Tag[];
}

const SIZE_CLASSES = [
  "text-xs",
  "text-sm",
  "text-base",
  "text-lg",
] as const;

function sizeClassFor(count: number, maxCount: number): string {
  if (maxCount <= 0) return SIZE_CLASSES[0];
  const ratio = count / maxCount;
  if (ratio >= 0.75) return SIZE_CLASSES[3];
  if (ratio >= 0.5) return SIZE_CLASSES[2];
  if (ratio >= 0.25) return SIZE_CLASSES[1];
  return SIZE_CLASSES[0];
}

export default function TagsCloud({ tags }: TagsCloudProps): JSX.Element {
  if (tags.length === 0) {
    return (
      <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Тегов пока нет.
      </p>
    );
  }
  const maxCount = Math.max(...tags.map((t) => t.article_count), 0);
  return (
    <ul className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
      {tags.map((tag) => (
        <li key={tag.name}>
          <Link
            href={`/articles?tags=${encodeURIComponent(tag.name)}`}
            className={`${sizeClassFor(tag.article_count, maxCount)} text-gray-800 hover:underline`}
          >
            {tag.name}
            <span className="ml-1 text-xs text-gray-500">
              ({tag.article_count})
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
