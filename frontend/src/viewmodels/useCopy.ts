import { useCallback, useState } from "react";

/**
 * Copy-to-clipboard with a transient "copied" acknowledgement.
 *
 * Shared by the message actions and code panels so the fallback path only
 * exists once: the Clipboard API needs a secure context, and NEXUS is
 * reachable over plain http in local dev.
 */
export function useCopy(resetMs = 1400) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(
    async (text: string) => {
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      setCopied(true);
      setTimeout(() => setCopied(false), resetMs);
    },
    [resetMs],
  );

  return { copied, copy };
}
