import { useMemo, useRef } from "react";
import { toJsxRuntime } from "hast-util-to-jsx-runtime";
import { createLowlight } from "lowlight";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import { useCopy } from "../viewmodels/useCopy";
import { languages } from "./languages";

// Highlighting runs here rather than as a rehype plugin: rehype-highlight
// statically imports highlight.js's ~37-language "common" set (+53 kB gzip
// on the critical path, since every message renders through Markdown), and
// no option turns that off. Driving lowlight directly bundles only the
// languages in ./languages.
const lowlight = createLowlight(languages);

/** "language-python" → "python"; anything unlabelled reads as "code". */
function languageOf(className?: string): string {
  return /language-([\w+#-]+)/.exec(className ?? "")?.[1] ?? "code";
}

/**
 * A fenced code block: language label, copy button, highlighted body.
 *
 * An unregistered language renders as plain text — models label fences with
 * anything, and a half-written fence mid-stream is normal, so this must
 * never throw.
 */
export default function CodeBlock({
  className,
  code,
}: {
  className?: string;
  code: string;
}) {
  const bodyRef = useRef<HTMLPreElement>(null);
  const { copied, copy } = useCopy();
  const lang = languageOf(className);

  // Streaming re-renders this on every token; memoising keeps highlighting
  // off the hot path when only the surrounding message changed.
  const highlighted = useMemo(() => {
    if (!lowlight.registered(lang)) return code;
    return toJsxRuntime(lowlight.highlight(lang, code), { Fragment, jsx, jsxs });
  }, [code, lang]);

  return (
    <div className="code-panel">
      <div className="code-head">
        <span className="code-lang">{lang}</span>
        <button
          className="code-copy"
          onClick={() => copy(bodyRef.current?.innerText ?? code)}
          title="Copy code"
        >
          {copied ? "✓ copied" : "⧉ copy"}
        </button>
      </div>
      <pre className="code-body" ref={bodyRef}>
        <code className={`hljs ${className ?? ""}`}>{highlighted}</code>
      </pre>
    </div>
  );
}
