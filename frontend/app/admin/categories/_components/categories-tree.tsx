/**
 * CategoriesTree — render-only компонент (#191).
 *
 * Extracted из page.tsx чтобы tests могли rendr'ить без async page
 * wrapper. Recursive <CategoryNode> рендерит дерево.
 */

import type { Category } from "@/lib/api/types";

interface NodeProps {
  node: Category;
  depth: number;
}

export function CategoryNode({ node, depth }: NodeProps): JSX.Element {
  return (
    <li className="text-sm">
      <div className="flex items-baseline gap-2 py-1">
        <span className="font-medium" style={{ paddingLeft: depth * 12 }}>
          {node.title}
        </span>
        <code
          className="text-[10px] text-gray-500"
          aria-label={`Slug ${node.slug}`}
        >
          {node.slug}
        </code>
        <span
          className="ml-auto tabular-nums text-xs text-gray-600"
          aria-label={`${node.article_count} articles`}
        >
          {node.article_count}
        </span>
      </div>
      {node.description ? (
        <p
          className="pl-3 pr-3 text-xs text-gray-500"
          style={{ paddingLeft: depth * 12 + 12 }}
        >
          {node.description}
        </p>
      ) : null}
      {node.children.length > 0 ? (
        <ul role="group" className="border-l border-gray-100">
          {node.children.map((child) => (
            <CategoryNode key={child.slug} node={child} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

interface TreeProps {
  data: Category[];
  error: string | null;
}

export default function CategoriesTree({ data, error }: TreeProps): JSX.Element {
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
        Категорий нет.
      </p>
    );
  }
  return (
    <ul
      role="tree"
      aria-label="Category tree"
      className="rounded-md border border-gray-200 bg-white p-2"
    >
      {data.map((node) => (
        <CategoryNode key={node.slug} node={node} depth={0} />
      ))}
    </ul>
  );
}
