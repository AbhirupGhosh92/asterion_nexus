import type { RefObject } from "react";
import type { Attachment, Profile } from "../models/types";

/** Model picker, attachments and the message input. */
export default function Composer({
  input, setInput, busy, uploading, pending, profile, model, setModel,
  composerRef, fileRef, onSend, onPickFiles, onDropAttachment,
}: {
  input: string;
  setInput: (v: string) => void;
  busy: boolean;
  uploading: boolean;
  pending: Attachment[];
  profile: Profile | null;
  model: string | null;
  setModel: (id: string) => void;
  composerRef: RefObject<HTMLInputElement>;
  fileRef: RefObject<HTMLInputElement>;
  onSend: () => void;
  onPickFiles: (files: FileList | null) => void;
  onDropAttachment: (id: string) => void;
}) {
  return (
    <footer className="composer-zone">
      {pending.length > 0 && (
        <div className="pending-row">
          {pending.map((a) => (
            <span key={a.meta.id} className="file-chip">
              {a.previewUrl ? <img className="chip-thumb" src={a.previewUrl} alt="" /> : "▤ "}
              {a.meta.name}
              <button className="chip-x" onClick={() => onDropAttachment(a.meta.id)}>✕</button>
            </span>
          ))}
        </div>
      )}
      <div className="composer">
        {profile && profile.models.length > 1 && (
          <select
            className="model-select"
            value={model ?? profile.models[0]?.id}
            onChange={(e) => setModel(e.target.value)}
            title="Model"
          >
            {profile.models.map((m) => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </select>
        )}
        <input
          ref={fileRef}
          type="file"
          accept="image/*,audio/*,video/*"
          multiple
          hidden
          onChange={(e) => onPickFiles(e.target.files)}
        />
        <button
          className={`composer-send attach-btn ${uploading ? "thinking-indicator" : ""}`}
          title="Attach image / audio / video"
          onClick={() => fileRef.current?.click()}
          disabled={uploading || busy}
        >
          {uploading ? "…" : "📎"}
        </button>
        <input
          ref={composerRef}
          className="composer-input"
          placeholder="> enter transmission…"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onSend()}
          autoFocus
        />
        <button
          className={`composer-send ${busy ? "thinking-indicator" : ""}`}
          onClick={onSend}
          disabled={busy || (!input.trim() && pending.length === 0)}
        >
          {busy ? "…" : "TRANSMIT"}
        </button>
      </div>
    </footer>
  );
}
