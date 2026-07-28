import { isValidElement } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import CodeBlock from "./CodeBlock";

/**
 * Markdown renderer for assistant output — tables, links, code, lists.
 *
 * Security: raw HTML is NOT enabled (no rehype-raw), so model output can't
 * inject markup. Links are forced to open in a new tab with noopener, since
 * anything an LLM or a web-search tool produces is untrusted.
 */
export default function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer nofollow" />
          ),
          // Wide tables scroll inside the bubble instead of stretching it.
          table: ({ ...props }) => (
            <div className="md-table-wrap">
              <table {...props} />
            </div>
          ),
          // Fenced blocks are handled at the `pre` level, not `code`: react
          // -markdown no longer passes an `inline` flag, and "is my parent a
          // pre?" is the only reliable way to tell a block from inline code.
          // Replacing `pre` outright means the inner `code` never renders,
          // so the panel owns the whole block.
          pre: ({ children }) => {
            const el = isValidElement<{ className?: string; children?: unknown }>(children)
              ? children
              : null;
            return (
              <CodeBlock
                className={el?.props.className}
                // Markdown fences always end in a newline the author didn't
                // type; keeping it would add a blank line to every copy.
                code={String(el?.props.children ?? "").replace(/\n$/, "")}
              />
            );
          },
          code: ({ className, children, ...props }) => (
            <code className={className ? className : "md-code-inline"} {...props}>
              {children}
            </code>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
