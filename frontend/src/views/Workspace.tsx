import { useEffect, useState } from "react";
import type { User } from "firebase/auth";
import { FIREBASE_ENABLED, signOutUser } from "../models/api";
import type { SpecialistAgent } from "../models/types";
import { useAgents } from "../viewmodels/useAgents";
import { useChat } from "../viewmodels/useChat";
import { useConversations } from "../viewmodels/useConversations";
import AdminPanel from "./admin/AdminPanel";
import AgentGallery from "./AgentGallery";
import Composer from "./Composer";
import MessageBubble from "./MessageBubble";
import Sidebar from "./Sidebar";
import UpgradeDialog from "./UpgradeDialog";

/**
 * The signed-in shell: sidebar + chat + composer, or the admin panel.
 * State lives in the viewmodels; this composes and lays out.
 */
export default function Workspace({ user }: { user: User | null }) {
  const convos = useConversations();
  const chat = useChat({
    activeId: convos.activeId,
    setActiveId: convos.setActiveId,
    onConversationsChanged: convos.refresh,
  });

  const { agents } = useAgents(chat.profile?.tier);

  const [health, setHealth] = useState<{ provider: string } | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false); // mobile drawer
  const [collapsed, setCollapsed] = useState(false); // desktop collapse
  const [showAdmin, setShowAdmin] = useState(false);
  // Which locked agent triggered the upgrade dialog (null agent = generic).
  const [upgrade, setUpgrade] = useState<{ agent: SpecialistAgent | null } | null>(null);

  useEffect(() => {
    convos.refresh();
    fetch("/api/healthz").then((r) => r.json()).then(setHealth).catch(() => {});
  }, [convos.refresh]);

  function toggleSidebar() {
    if (window.matchMedia("(max-width: 820px)").matches) setSidebarOpen((v) => !v);
    else setCollapsed((v) => !v);
  }

  function newChat() {
    chat.reset();
    setSidebarOpen(false);
  }

  async function openConversation(id: string) {
    setSidebarOpen(false);
    if (id === convos.activeId) return;
    const loaded = await convos.open(id);
    if (loaded) chat.load(loaded);
  }

  async function removeConversation(id: string) {
    await convos.remove(id);
    if (id === convos.activeId) newChat();
  }

  /** Point the next turn at this agent; the composer stays where it is. */
  function deployAgent(agent: SpecialistAgent) {
    chat.setModel(agent.id);
    chat.composerRef.current?.focus();
  }

  const { profile } = chat;
  const identity = profile
    ? `${user?.email ?? profile.uid} · ${profile.tier.toUpperCase()}`
    : user?.email ?? "…";

  return (
    <div className={`layout ${collapsed ? "layout-collapsed" : ""}`}>
      {sidebarOpen && <div className="scrim" onClick={() => setSidebarOpen(false)} />}

      <Sidebar
        conversations={convos.conversations}
        activeId={convos.activeId}
        open={sidebarOpen}
        onNewChat={newChat}
        onOpen={openConversation}
        onDelete={removeConversation}
      />

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
                className={`hud-chip hud-quota ${profile.quota.remaining === 0 ? "hud-quota-out" : ""}`}
                title={`${profile.quota.used} of ${profile.quota.limit} calls used this month · resets ${profile.quota.resets_on}`}
              >
                ⚡ {profile.quota.remaining}/{profile.quota.limit}
              </span>
            )}
            {profile?.tier === "free" && (
              <button
                className="hud-chip hud-upgrade"
                title="See what PRO unlocks"
                onClick={() => setUpgrade({ agent: null })}
              >
                ⬆ PRO
              </button>
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
          <main className="chat terminal-panel" ref={chat.scrollRef} onScroll={chat.handleScroll}>
            {chat.messages.length === 0 && (
              <div className="home">
                <div className="empty">
                  <div className="empty-glyph">◢◤</div>
                  <p>CHANNEL OPEN. TRANSMIT WHEN READY.</p>
                  <p className="empty-sub">
                    auth → guardrails → model → memory · every message rides the full pipeline
                  </p>
                </div>
                <AgentGallery
                  agents={agents}
                  activeId={chat.model}
                  onDeploy={deployAgent}
                  onLocked={(agent) => setUpgrade({ agent })}
                />
              </div>
            )}
            {chat.messages.map((m, idx) => (
              <MessageBubble
                key={m.id}
                message={m}
                isLast={idx === chat.messages.length - 1}
                busy={chat.busy}
                onAnswer={(answer) => chat.send(answer)}
                onOther={() => chat.composerRef.current?.focus()}
                onRetry={chat.retry}
              />
            ))}
          </main>
        )}

        {!showAdmin && !chat.pinned && chat.messages.length > 0 && (
          <button className="jump-latest" onClick={() => chat.scrollToBottom(true)}>
            ↓ jump to latest
          </button>
        )}

        {!showAdmin && (
          <Composer
            input={chat.input}
            setInput={chat.setInput}
            busy={chat.busy}
            uploading={chat.uploading}
            pending={chat.pending}
            profile={profile}
            model={chat.model}
            setModel={chat.setModel}
            composerRef={chat.composerRef}
            fileRef={chat.fileRef}
            onSend={() => chat.send()}
            onPickFiles={chat.pickFiles}
            onDropAttachment={chat.dropAttachment}
          />
        )}
      </div>

      {upgrade && (
        <UpgradeDialog
          agent={upgrade.agent}
          tier={profile?.tier ?? "free"}
          onClose={() => setUpgrade(null)}
        />
      )}
    </div>
  );
}
