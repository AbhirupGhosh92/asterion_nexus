import { useState } from "react";

export interface AskOption {
  label: string;
  description?: string;
}

export interface AskBlock {
  question: string;
  options: AskOption[];
  multiSelect?: boolean;
}

/** Pulls ```ask {json}``` blocks out of a message, keeping the prose around them. */
export function parseAsk(content: string): { text: string; ask: AskBlock | null } {
  const match = content.match(/```ask\s*\n([\s\S]*?)```/);
  if (!match) return { text: content, ask: null };
  try {
    const parsed = JSON.parse(match[1]);
    if (!parsed?.question || !Array.isArray(parsed.options) || parsed.options.length === 0) {
      return { text: content, ask: null };
    }
    return {
      text: (content.slice(0, match.index) + content.slice(match.index! + match[0].length)).trim(),
      ask: {
        question: String(parsed.question),
        multiSelect: Boolean(parsed.multiSelect),
        options: parsed.options
          .filter((o: AskOption) => o?.label)
          .map((o: AskOption) => ({ label: String(o.label), description: o.description })),
      },
    };
  } catch {
    return { text: content, ask: null }; // malformed → leave it as text
  }
}

/**
 * Renders an LLM question as clickable options. `live` is false for older
 * turns, which stay visible but inert so history reads correctly.
 */
export default function AskCard({
  ask,
  live,
  onAnswer,
  onOther,
}: {
  ask: AskBlock;
  live: boolean;
  onAnswer: (answer: string) => void;
  onOther: () => void;
}) {
  const [picked, setPicked] = useState<string[]>([]);

  function toggle(label: string) {
    if (!live) return;
    if (ask.multiSelect) {
      setPicked((cur) =>
        cur.includes(label) ? cur.filter((l) => l !== label) : [...cur, label],
      );
    } else {
      onAnswer(label);
    }
  }

  return (
    <div className={`ask ${live ? "" : "ask-done"}`}>
      <div className="ask-q">
        <span className="ask-icon">◆</span>
        {ask.question}
      </div>
      <div className="ask-options">
        {ask.options.map((o) => {
          const on = picked.includes(o.label);
          return (
            <button
              key={o.label}
              className={`ask-option ${on ? "ask-option-on" : ""}`}
              onClick={() => toggle(o.label)}
              disabled={!live}
            >
              <span className="ask-label">
                {ask.multiSelect && <span className="ask-box">{on ? "◉" : "○"}</span>}
                {o.label}
              </span>
              {o.description && <span className="ask-desc">{o.description}</span>}
            </button>
          );
        })}
      </div>
      {live && (
        <div className="ask-actions">
          {ask.multiSelect && (
            <button
              className="composer-send ask-submit"
              disabled={picked.length === 0}
              onClick={() => onAnswer(picked.join(", "))}
            >
              CONFIRM{picked.length ? ` (${picked.length})` : ""}
            </button>
          )}
          <button className="ask-other" onClick={onOther}>
            ✎ something else
          </button>
        </div>
      )}
    </div>
  );
}
