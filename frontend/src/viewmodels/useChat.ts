import { useCallback, useEffect, useRef, useState } from "react";
import { chatStream, fetchProfile, uploadFile } from "../models/api";
import type { AgentStep, Attachment, ChatMessage, Profile, UiMessage } from "../models/types";

let nextId = 1;

/**
 * A live conversation: message list, streaming, attachments, model choice
 * and scroll position. Views render what this returns and call its actions —
 * they hold no logic of their own.
 */
export function useChat(opts: {
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  onConversationsChanged: () => void;
}) {
  const { activeId, setActiveId, onConversationsChanged } = opts;

  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [pending, setPending] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refreshProfile = useCallback(() => {
    fetchProfile().then(setProfile).catch(() => {});
  }, []);

  useEffect(() => {
    refreshProfile();
  }, [refreshProfile]);

  // ---- scrolling --------------------------------------------------------
  // Stay pinned to the newest content, but only while the user is already at
  // the bottom, so scrolling up to read isn't yanked back mid-stream.
  const atBottomRef = useRef(true);
  const [pinned, setPinned] = useState(true);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    atBottomRef.current = bottom;
    setPinned(bottom);
  }, []);

  const scrollToBottom = useCallback((smooth = false) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    atBottomRef.current = true;
    setPinned(true);
  }, []);

  useEffect(() => {
    // Instant, not smooth: streaming fires this per token and smooth
    // animations queue up and lag behind the text.
    if (atBottomRef.current) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  // ---- actions ----------------------------------------------------------

  const reset = useCallback(() => {
    setActiveId(null);
    setMessages([]);
    atBottomRef.current = true;
    setPinned(true);
  }, [setActiveId]);

  const load = useCallback((loaded: ChatMessage[]) => {
    setMessages(loaded.map((m) => ({ ...m, id: nextId++ })));
    atBottomRef.current = true; // open a conversation at its latest message
  }, []);

  const pickFiles = useCallback(async (files: FileList | null) => {
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
  }, []);

  const dropAttachment = useCallback((id: string) => {
    setPending((cur) => cur.filter((p) => p.meta.id !== id));
  }, []);

  const send = useCallback(
    async (override?: string) => {
      const text = (override ?? input).trim();
      if ((!text && pending.length === 0) || busy) return;

      const attachments = pending;
      setPending([]);
      if (override === undefined) setInput("");
      setBusy(true);

      const userMsg: UiMessage = {
        id: nextId++, role: "user", content: text || "(attachment)", attachments,
      };
      const botMsg: UiMessage = { id: nextId++, role: "assistant", content: "", streaming: true };
      const history = [...messages, userMsg];
      setMessages([...history, botMsg]);

      const patch = (fn: (m: UiMessage) => UiMessage) =>
        setMessages((cur) => cur.map((m) => (m.id === botMsg.id ? fn(m) : m)));

      try {
        await chatStream(
          history.map(({ role, content }) => ({ role, content })),
          {
            onToken: (token) => patch((m) => ({ ...m, content: m.content + token })),
            onStep: (step: AgentStep) =>
              patch((m) => ({ ...m, steps: [...(m.steps ?? []), step] })),
            onMeta: (cid) => {
              if (cid) setActiveId(cid);
            },
            onTitle: () => onConversationsChanged(),
          },
          activeId,
          { model, attachments: attachments.map((a) => a.meta.id) },
        );
        onConversationsChanged();
      } catch (err) {
        const raw = String(err);
        // A 429 is the monthly quota, not a failure — say so in plain language.
        const quotaHit = raw.includes("429");
        const detail = raw.match(/"detail":"([^"]+)"/)?.[1];
        patch((m) => ({
          ...m,
          content: quotaHit
            ? `⚠ QUOTA EXHAUSTED — ${detail ?? "You've used all your API calls for this month."}`
            : `⚠ TRANSMISSION ERROR — ${raw}`,
          guardrail: true,
        }));
      } finally {
        refreshProfile();
        patch((m) => ({ ...m, streaming: false }));
        setBusy(false);
      }
    },
    [activeId, busy, input, messages, model, onConversationsChanged, pending,
     refreshProfile, setActiveId],
  );

  return {
    messages, input, setInput, busy, profile, model, setModel,
    pending, uploading, pinned,
    scrollRef, composerRef, fileRef,
    send, pickFiles, dropAttachment, reset, load, handleScroll, scrollToBottom,
  };
}
