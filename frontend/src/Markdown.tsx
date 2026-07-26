import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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
          code: ({ className, children, ...props }) => {
            const inline = !String(className || "").includes("language-");
            return inline ? (
              <code className="md-code-inline" {...props}>
                {children}
              </code>
            ) : (
              <code className={className} {...props}>
                {children}
              </code>
            );
          },
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
