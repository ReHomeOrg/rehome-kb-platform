/**
 * Server Component — markdown renderer для body_markdown.
 *
 * Используется `react-markdown` БЕЗ `rehype-raw` — raw HTML в body
 * escape'ится (нет XSS). GFM (tables, strikethrough, autolink) включен.
 *
 * Если в будущем потребуется HTML в body_markdown (e.g., editor
 * пишет HTML) — backlog с DOMPurify gate.
 */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ArticleMarkdownProps {
  content: string;
}

export default function ArticleMarkdown({
  content,
}: ArticleMarkdownProps): JSX.Element {
  return (
    <div className="prose prose-gray max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a
              href={href}
              className="font-medium text-brand-strong underline decoration-brand-strong/40 decoration-1 underline-offset-2 hover:text-ink hover:decoration-brand-strong"
            >
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
