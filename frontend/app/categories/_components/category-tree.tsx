/**
 * Recursive Category tree (UI.3 #79) — Server Component.
 *
 * Render каждого node = link на `/articles?category=<slug>` + count.
 * Дети — вложенный <ul> с отступом по depth.
 */

import Link from "next/link";

import type { Category } from "@/lib/api/types";

interface CategoryTreeProps {
  nodes: Category[];
}

interface CategoryNodeProps {
  node: Category;
  depth: number;
}

function CategoryNode({ node, depth }: CategoryNodeProps): JSX.Element {
  return (
    <li className="flex flex-col gap-1">
      <div
        className="flex items-baseline gap-2"
        style={{ paddingLeft: `${depth * 16}px` }}
      >
        <Link
          href={`/articles?category=${encodeURIComponent(node.slug)}`}
          className="text-sm hover:underline"
        >
          {node.title}
        </Link>
        <span className="text-xs text-gray-500">
          ({node.article_count})
        </span>
      </div>
      {node.children.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {node.children.map((child) => (
            <CategoryNode key={child.slug} node={child} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export default function CategoryTree({ nodes }: CategoryTreeProps): JSX.Element {
  if (nodes.length === 0) {
    return (
      <p className="rounded-md border border-gray-200 bg-gray-50 p-4 text-sm text-gray-600">
        Категории пока не созданы.
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-2">
      {nodes.map((node) => (
        <CategoryNode key={node.slug} node={node} depth={0} />
      ))}
    </ul>
  );
}
