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
      <div style={{ paddingLeft: `${depth * 16}px` }}>
        <Link
          href={`/articles?category=${encodeURIComponent(node.slug)}`}
          aria-label={`Открыть категорию ${node.title}`}
          className="group flex items-center justify-between rounded-md border border-gray-200 bg-white px-3 py-2 text-sm transition hover:border-brand hover:bg-brand-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40"
        >
          <span className="font-medium text-gray-900">{node.title}</span>
          <span className="ml-3 flex shrink-0 items-center gap-2 text-xs text-gray-500">
            <span>({node.article_count})</span>
            <span className="text-brand-strong transition group-hover:translate-x-0.5">→</span>
          </span>
        </Link>
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
