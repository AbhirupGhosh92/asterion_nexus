import { useEffect, useState } from "react";
import { fetchUploadUrl } from "../models/api";
import type { AgentStep, UiMessage } from "../models/types";
import AskCard, { parseAsk } from "./AskCard";
import Markdown from "./Markdown";

/** Renders an [image:<id>] token as an authenticated image. */
function GeneratedImage({ fileId }: { fileId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchUploadUrl(fileId).then(setUrl).catch(() => setFailed(true));
  }, [fileId]);

  if (failed) return <span className="file-chip">⚠ image unavailable</span>;
  if (!url) return <span className="img-loading thinking-indicator">◢ rendering…</span>;
  return <img className="msg-img msg-img-generated" src={url} alt="generated image" />;
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
}: {
  message: UiMessage;
  isLast: boolean;
  busy: boolean;
  onAnswer: (answer: string) => void;
  onOther: () => void;
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
                <img key={a.meta.id} className="msg-img" src={a.previewUrl} alt={a.meta.name} />
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
    </div>
  );
}
