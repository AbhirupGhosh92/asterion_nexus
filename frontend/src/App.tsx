import { useCallback, useEffect, useRef, useState } from "react";
import type { User } from "firebase/auth";
import AdminPanel from "./Admin";
import AskCard, { parseAsk } from "./AskCard";
import Markdown from "./Markdown";
import {
  chatStream,
  deleteConversation,
  fetchProfile,
  fetchUploadUrl,
  FIREBASE_ENABLED,
  getConversation,
  listConversations,
  signInWithGoogle,
  signOutUser,
  uploadFile,
  watchAuth,
  type AgentStep,
  type ChatMessage,
  type ConversationMeta,
  type Profile,
  type UploadMeta,
} from "./lib/apiClient";

/** Renders an [image:<id>] media token as an authenticated image. */
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
 * Splits message text into generated-image tokens and text segments.
 * `markdown` is on for assistant output (tables, links, code) and off for
 * user messages, which are shown exactly as typed.
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

interface Attachment {
  meta: UploadMeta;
  previewUrl: string | null; // object URL for images
}

interface UiMessage extends ChatMessage {
  id: number;
  streaming?: boolean;
  guardrail?: boolean;
  attachments?: Attachment[];
}

/** The agent's autonomous decisions, rendered as an expandable trace. */
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
                <span className="trace-tool" key={t}>
                  ⚙ {t}
                </span>
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
                  {s.observation.length > 400
                    ? s.observation.slice(0, 400) + " …"
                    : s.observation}
                </code>
              </div>
            )}
          </div>
        ))}
    </div>
  );
}

let nextId = 1;

type AuthState = { status: "loading" } | { status: "out" } | { status: "in"; user: User | null };

export default function App() {
  // Without Firebase config (offline dev), skip the gate entirely.
  const [auth, setAuth] = useState<AuthState>(
    FIREBASE_ENABLED ? { status: "loading" } : { status: "in", user: null },
  );

  useEffect(() => {
    if (!FIREBASE_ENABLED) return;
    return watchAuth((user) => setAuth(user ? { status: "in", user } : { status: "out" }));
  }, []);

  if (auth.status === "loading") {
    return (
      <div className="shell gate">
        <div className="gate-glyph thinking-indicator">◢◤</div>
        <p className="gate-text">ESTABLISHING LINK…</p>
      </div>
    );
  }

  if (auth.status === "out") {
    return <AuthGate />;
  }

  return <Workspace user={auth.user} />;
}

function AuthGate() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function login() {
    setBusy(true);
    setError(null);
    try {
      await signInWithGoogle();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shell gate">
      <div className="gate-panel terminal-panel neon-border">
        <div className="gate-glyph">◢◤</div>
        <h1 className="gate-title">
          NEXUS<span className="hud-dim">://</span>AI
        </h1>
        <p className="gate-text">IDENTITY VERIFICATION REQUIRED</p>
        <p className="gate-sub">access to the grid is gated · sign in to open a channel</p>
        <button className="composer-send gate-btn" onClick={login} disabled={busy}>
          {busy ? "AUTHENTICATING…" : "AUTHENTICATE WITH GOOGLE"}
        </button>
        {error && <p className="gate-error">⚠ {error}</p>}
      </div>
    </div>
  );
}

function Workspace({ user }: { user: User | null }) {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [health, setHealth] = useState<{ provider: string } | null>(null);
  const [conversations, setConversations] = useState<ConversationMeta[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile drawer
  const [collapsed, setCollapsed] = useState(false); // desktop collapse
  const [showAdmin, setShowAdmin] = useState(false);
  const [model, setModel] = useState<string | null>(null);
  const [pending, setPending] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLInputElement>(null);

  const refreshConversations = useCallback(() => {
    listConversations().then(setConversations).catch(() => {});
  }, []);

  const refreshProfile = useCallback(() => {
    fetchProfile().then(setProfile).catch(() => {});
  }, []);

  useEffect(() => {
    refreshProfile();
    fetch("/api/healthz")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => {});
    refreshConversations();
  }, [refreshConversations, refreshProfile]);

  // Stay pinned to the newest content — but only while the user is already at
  // the bottom, so scrolling up to read isn't yanked back mid-stream.
  const atBottomRef = useRef(true);
  const [pinned, setPinned] = useState(true);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    atBottomRef.current = bottom;
    setPinned(bottom);
  }

  function scrollToBottom(smooth = false) {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    atBottomRef.current = true;
    setPinned(true);
  }

  useEffect(() => {
    // Instant (not smooth) because streaming fires this per token and smooth
    // animations queue up and lag behind the text.
    if (atBottomRef.current) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  function newChat() {
    setActiveId(null);
    setMessages([]);
    setSidebarOpen(false);
    atBottomRef.current = true;
    setPinned(true);
  }

  async function openConversation(id: string) {
    setSidebarOpen(false);
    if (id === activeId) return;
    try {
      const conv = await getConversation(id);
      setActiveId(id);
      // steps ride along so a replayed agent turn still shows its decisions
      setMessages(conv.messages.map((m) => ({ ...m, id: nextId++ })));
      atBottomRef.current = true; // open a conversation at its latest message
    } catch {
      /* stale entry; refresh list */
      refreshConversations();
    }
  }

  async function removeConversation(id: string) {
    await deleteConversation(id);
    if (id === activeId) newChat();
    refreshConversations();
  }

  async function pickFiles(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    try {
      for (const file of Array.from(files).slice(0, 5)) {
        const meta = await uploadFile(file);
        const previewUrl = file.type.startsWith("image/") ? URL.createObjectURL(file) : null;
        setPending((cur) => [...cur, { meta, previewUrl }]);
      }
    } catch (err) {
      alert(String(err));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function send(override?: string) {
    const text = (override ?? input).trim();
    if ((!text && pending.length === 0) || busy) return;
    const attachments = pending;
    setPending([]);
    if (override === undefined) setInput("");
    setBusy(true);

    const userMsg: UiMessage = {
      id: nextId++,
      role: "user",
      content: text || "(attachment)",
      attachments,
    };
    const botMsg: UiMessage = { id: nextId++, role: "assistant", content: "", streaming: true };
    const history = [...messages, userMsg];
    setMessages([...history, botMsg]);

    try {
      await chatStream(
        history.map(({ role, content }) => ({ role, content })),
        {
          onToken: (token) =>
            setMessages((cur) =>
              cur.map((m) => (m.id === botMsg.id ? { ...m, content: m.content + token } : m)),
            ),
          onStep: (step) =>
            setMessages((cur) =>
              cur.map((m) =>
                m.id === botMsg.id ? { ...m, steps: [...(m.steps ?? []), step] } : m,
              ),
            ),
          onMeta: (cid) => {
            if (cid) setActiveId(cid);
          },
          onTitle: () => refreshConversations(),
        },
        activeId,
        { model, attachments: attachments.map((a) => a.meta.id) },
      );
      refreshConversations();
    } catch (err) {
      const raw = String(err);
      // A 429 is the monthly quota, not a failure — say so in plain language.
      const quotaHit = raw.includes("429");
      const detail = raw.match(/"detail":"([^"]+)"/)?.[1];
      setMessages((cur) =>
        cur.map((m) =>
          m.id === botMsg.id
            ? {
                ...m,
                content: quotaHit
                  ? `⚠ QUOTA EXHAUSTED — ${detail ?? "You've used all your API calls for this month."}`
                  : `⚠ TRANSMISSION ERROR — ${raw}`,
                guardrail: true,
              }
            : m,
        ),
      );
    } finally {
      refreshProfile();
      setMessages((cur) => cur.map((m) => (m.id === botMsg.id ? { ...m, streaming: false } : m)));
      setBusy(false);
    }
  }

  const identity = profile
    ? `${user?.email ?? profile.uid} · ${profile.tier.toUpperCase()}`
    : user?.email ?? "…";

  function toggleSidebar() {
    if (window.matchMedia("(max-width: 820px)").matches) {
      setSidebarOpen((v) => !v); // drawer overlay
    } else {
      setCollapsed((v) => !v); // collapse the column
    }
  }

  return (
    <div className={`layout ${collapsed ? "layout-collapsed" : ""}`}>
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <button className="composer-send new-chat" onClick={newChat}>
          + NEW CHANNEL
        </button>
        <nav className="conv-list">
          {conversations.length === 0 && <p className="conv-empty">no transmissions yet</p>}
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`conv-item ${c.id === activeId ? "conv-active" : ""}`}
              onClick={() => openConversation(c.id)}
            >
              <span className="conv-title">{c.title}</span>
              <button
                className="conv-delete"
                title="Delete"
                onClick={(e) => {
                  e.stopPropagation();
                  removeConversation(c.id);
                }}
              >
                ✕
              </button>
            </div>
          ))}
        </nav>
      </aside>

      <div className="shell">
        <header className="hud">
          <div className="hud-left">
            <button className="hud-chip hamburger" title="Toggle sidebar" onClick={toggleSidebar}>
              ☰
            </button>
            <div className="hud-brand glitch-hover">
              <span className="hud-glyph">◢</span> NEXUS<span className="hud-dim">://</span>AI
            </div>
          </div>
          <div className="hud-status">
            <span className="hud-chip hud-link">
              <span className={`dot ${health ? "dot-on" : "dot-off"}`} />
              {health ? `LINK:${health.provider.toUpperCase()}` : "LINK:OFFLINE"}
            </span>
            {profile?.quota?.enforced && profile.quota.limit >= 0 && (
              <span
                className={`hud-chip hud-quota ${
                  profile.quota.remaining === 0 ? "hud-quota-out" : ""
                }`}
                title={`${profile.quota.used} of ${profile.quota.limit} calls used this month · resets ${profile.quota.resets_on}`}
              >
                ⚡ {profile.quota.remaining}/{profile.quota.limit}
              </span>
            )}
            <span className="hud-chip hud-tier">{identity}</span>
            {profile?.is_admin && (
              <button
                className={`hud-chip hud-admin ${showAdmin ? "hud-admin-on" : ""}`}
                onClick={() => setShowAdmin((v) => !v)}
              >
                ⚙ ADMIN
              </button>
            )}
            {FIREBASE_ENABLED && (
              <button className="hud-chip hud-signout" onClick={() => signOutUser()}>
                ⏻ EXIT
              </button>
            )}
          </div>
        </header>

        {showAdmin ? (
          <AdminPanel onClose={() => setShowAdmin(false)} />
        ) : (
          <main className="chat terminal-panel" ref={scrollRef} onScroll={handleScroll}>
            {messages.length === 0 && (
              <div className="empty">
                <div className="empty-glyph">◢◤</div>
                <p>CHANNEL OPEN. TRANSMIT WHEN READY.</p>
                <p className="empty-sub">
                  auth → guardrails → model → memory · every message rides the full pipeline
                </p>
              </div>
            )}
            {messages.map((m, idx) => {
              const isAssistant = m.role === "assistant" && !m.guardrail;
              // While streaming, an ask block is still half-written — hide the
              // raw JSON until it parses instead of flashing it at the user.
              const partialAsk = m.streaming && m.content.includes("```ask");
              const { text, ask } = isAssistant && !m.streaming
                ? parseAsk(m.content)
                : { text: partialAsk ? m.content.slice(0, m.content.indexOf("```ask")) : m.content, ask: null };
              return (
              <div key={m.id} className={`msg msg-${m.role} ${m.guardrail ? "msg-guardrail" : ""}`}>
                <div className="msg-label">{m.role === "user" ? "YOU" : "NEXUS"}</div>
                <div className="msg-body">
                  {m.attachments && m.attachments.length > 0 && (
                    <div className="msg-attachments">
                      {m.attachments.map((a) =>
                        a.previewUrl ? (
                          <img key={a.meta.id} className="msg-img" src={a.previewUrl} alt={a.meta.name} />
                        ) : (
                          <span key={a.meta.id} className="file-chip">
                            ▤ {a.meta.name}
                          </span>
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
                    <AskCard
                      ask={ask}
                      live={idx === messages.length - 1 && !busy}
                      onAnswer={(answer) => send(answer)}
                      onOther={() => composerRef.current?.focus()}
                    />
                  )}
                </div>
              </div>
              );
            })}
          </main>
        )}

        {!showAdmin && !pinned && messages.length > 0 && (
          <button className="jump-latest" onClick={() => scrollToBottom(true)}>
            ↓ jump to latest
          </button>
        )}

        {!showAdmin && (
          <footer className="composer-zone">
            {pending.length > 0 && (
              <div className="pending-row">
                {pending.map((a) => (
                  <span key={a.meta.id} className="file-chip">
                    {a.previewUrl ? (
                      <img className="chip-thumb" src={a.previewUrl} alt="" />
                    ) : (
                      "▤ "
                    )}
                    {a.meta.name}
                    <button
                      className="chip-x"
                      onClick={() => setPending((cur) => cur.filter((p) => p.meta.id !== a.meta.id))}
                    >
                      ✕
                    </button>
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
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              )}
              <input
                ref={fileRef}
                type="file"
                accept="image/*,audio/*,video/*"
                multiple
                hidden
                onChange={(e) => pickFiles(e.target.files)}
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
                onKeyDown={(e) => e.key === "Enter" && send()}
                autoFocus
              />
              <button
                className={`composer-send ${busy ? "thinking-indicator" : ""}`}
                onClick={() => send()}
                disabled={busy || (!input.trim() && pending.length === 0)}
              >
                {busy ? "…" : "TRANSMIT"}
              </button>
            </div>
          </footer>
        )}
      </div>
    </div>
  );
}
