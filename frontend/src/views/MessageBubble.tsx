import { useEffect, useState } from "react";
import { fetchUploadUrl } from "../models/api";
import type { AgentStep, UiMessage } from "../models/types";
import AskCard, { parseAsk } from "./AskCard";
import Markdown from "./Markdown";

/** Saves an already-fetched object URL to disk under a readable name. */
function downloadUrl(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** An image with a hover download button. */
function ImageWithDownload({
  url, filename, alt, className,
}: { url: string; filename: string; alt: string; className: string }) {
  return (
    <span className="img-wrap">
      <img className={className} src={url} alt={alt} />
      <button
        className="img-download"
        title={`Download ${filename}`}
        onClick={() => downloadUrl(url, filename)}
      >
        ↓
      </button>
    </span>
  );
}

/** Renders an [image:<id>] token as an authenticated, downloadable image. */
function GeneratedImage({ fileId }: { fileId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchUploadUrl(fileId).then(setUrl).catch(() => setFailed(true));
  }, [fileId]);

  if (failed) return <span className="file-chip">⚠ image unavailable</span>;
  if (!url) return <span className="img-loading thinking-indicator">◢ rendering…</span>;
  return (
    <ImageWithDownload
      url={url}
      filename={`nexus-${fileId.slice(0, 8)}.png`}
      alt="generated image"
      className="msg-img msg-img-generated"
    />
  );
}

/** Copy / retry actions shown under a user message. */
function MessageActions({ text, onRetry }: { text: string; onRetry?: () => void }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard API needs a secure context; fall back to a hidden textarea.
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div className="msg-actions">
      <button className="msg-action" onClick={copy} title="Copy this message">
        {copied ? "✓ copied" : "⧉ copy"}
      </button>
      {onRetry && (
        <button className="msg-action" onClick={onRetry} title="Send this message again">
          ↻ retry
        </button>
      )}
    </div>
  );
}

const IMAGE_TOKEN = /\[image:([a-f0-9]{32})\]/g;

/**
 * Splits text into generated-image tokens and prose. Markdown is on for
 * assistant output (tables, links, code) and off for user messages, which
 * are shown exactly as typed.
 */
function MessageContent({ content, markdown }: { content: string; markdown?: boolean }) {
  const parts: (string | { id: string })[] = [];
  let last = 0;
  for (const m of content.matchAll(IMAGE_TOKEN)) {
    if (m.index! > last) parts.push(content.slice(last, m.index));
    parts.push({ id: m[1] });
    last = m.index! + m[0].length;
  }
  if (last < content.length) parts.push(content.slice(last));

  return (
    <>
      {parts.map((p, i) =>
        typeof p !== "string" ? (
          <GeneratedImage key={i} fileId={p.id} />
        ) : markdown ? (
          <Markdown key={i}>{p}</Markdown>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

/** The agent's autonomous decisions, as an expandable trace. */
function DecisionTrace({ steps, live }: { steps: AgentStep[]; live?: boolean }) {
  const [open, setOpen] = useState(true);
  if (steps.length === 0) return null;

  return (
    <div className="trace">
      <button className="trace-head" onClick={() => setOpen((v) => !v)}>
        <span className="trace-caret">{open ? "▾" : "▸"}</span>
        ◈ DECISION TRACE
        <span className="trace-count">
          {steps.length} step{steps.length === 1 ? "" : "s"}
        </span>
        {live && <span className="trace-live">● THINKING</span>}
      </button>
      {open &&
        steps.map((s, i) => (
          <div className="trace-step" key={s.position ?? i}>
            <div className="trace-step-head">
              <span className="trace-num">{String(i + 1).padStart(2, "0")}</span>
              {(s.tool ?? "reasoning").split(";").filter(Boolean).map((t) => (
                <span className="trace-tool" key={t}>⚙ {t}</span>
              ))}
            </div>
            {s.thought && <div className="trace-thought">“{s.thought.trim()}”</div>}
            {s.tool_input && (
              <div className="trace-line">
                <span className="trace-label">ARGS</span>
                <code>{s.tool_input.slice(0, 300)}</code>
              </div>
            )}
            {s.observation && (
              <div className="trace-line">
                <span className="trace-label">RESULT</span>
                <code className="trace-obs">
                  {s.observation.length > 400 ? s.observation.slice(0, 400) + " …" : s.observation}
                </code>
              </div>
            )}
          </div>
        ))}
    </div>
  );
}

export default function MessageBubble({
  message: m,
  isLast,
  busy,
  onAnswer,
  onOther,
  onRetry,
}: {
  message: UiMessage;
  isLast: boolean;
  busy: boolean;
  onAnswer: (answer: string) => void;
  onOther: () => void;
  onRetry?: (id: number) => void;
}) {
  const isAssistant = m.role === "assistant" && !m.guardrail;
  // While streaming, an ask block is still half-written — hide the raw JSON
  // until it parses instead of flashing it at the user.
  const partialAsk = m.streaming && m.content.includes("```ask");
  const { text, ask } =
    isAssistant && !m.streaming
      ? parseAsk(m.content)
      : {
          text: partialAsk ? m.content.slice(0, m.content.indexOf("```ask")) : m.content,
          ask: null,
        };

  return (
    <div className={`msg msg-${m.role} ${m.guardrail ? "msg-guardrail" : ""}`}>
      <div className="msg-label">{m.role === "user" ? "YOU" : "NEXUS"}</div>
      <div className="msg-body">
        {m.attachments && m.attachments.length > 0 && (
          <div className="msg-attachments">
            {m.attachments.map((a) =>
              a.previewUrl ? (
                <ImageWithDownload
                  key={a.meta.id}
                  url={a.previewUrl}
                  filename={a.meta.name}
                  alt={a.meta.name}
                  className="msg-img"
                />
              ) : (
                <span key={a.meta.id} className="file-chip">▤ {a.meta.name}</span>
              ),
            )}
          </div>
        )}
        {m.role === "assistant" && m.steps && m.steps.length > 0 && (
          <DecisionTrace steps={m.steps} live={m.streaming} />
        )}
        <MessageContent content={text} markdown={isAssistant} />
        {partialAsk && <span className="ask-pending">◆ preparing options…</span>}
        {m.streaming && <span className="cursor">▊</span>}
        {ask && (
          <AskCard ask={ask} live={isLast && !busy} onAnswer={onAnswer} onOther={onOther} />
        )}
      </div>
      {m.role === "user" && !m.streaming && (
        <MessageActions
          text={m.content}
          onRetry={onRetry && !busy ? () => onRetry(m.id) : undefined}
        />
      )}
    </div>
  );
}
