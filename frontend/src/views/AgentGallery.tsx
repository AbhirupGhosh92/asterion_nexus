import type { SpecialistAgent } from "../models/types";

/**
 * The homepage roster of specialist agents forged by the admin in Dify.
 *
 * Agents above the user's tier are shown, not hidden — that's the point of
 * the section — but they carry a lock and route to the upgrade dialog
 * instead of the composer.
 */
export default function AgentGallery({
  agents,
  activeId,
  onDeploy,
  onLocked,
}: {
  agents: SpecialistAgent[];
  activeId: string | null;
  onDeploy: (agent: SpecialistAgent) => void;
  onLocked: (agent: SpecialistAgent) => void;
}) {
  if (agents.length === 0) return null;

  return (
    <section className="gallery">
      <div className="gallery-head">
        <span className="gallery-title">◈ SPECIALIST UNITS</span>
        <span className="gallery-sub">purpose-built agents · tools + autonomous reasoning</span>
      </div>

      <div className="gallery-grid">
        {agents.map((a) => {
          const offline = !a.online && !a.locked;
          return (
            <button
              key={a.id}
              className={`agent-card ${a.locked ? "agent-card-locked" : ""} ${
                activeId === a.id ? "agent-card-active" : ""
              } ${offline ? "agent-card-offline" : ""}`}
              disabled={offline}
              onClick={() => (a.locked ? onLocked(a) : onDeploy(a))}
              title={a.locked ? `${a.min_tier.toUpperCase()} tier required` : a.description}
            >
              <div className="agent-card-head">
                <span className="agent-name">{a.label}</span>
                {a.locked && <span className="agent-badge agent-badge-pro">🔒 PRO</span>}
                {activeId === a.id && <span className="agent-badge agent-badge-on">● ACTIVE</span>}
                <span
                  className="agent-engine"
                  title={a.engine === "langgraph"
                    ? "LangGraph deep agent — runs in the backend"
                    : "Dify engine agent"}
                >
                  {a.engine === "langgraph" ? "◈ deep" : "⚡ dify"}
                </span>
              </div>

              <p className="agent-brief">{a.description || "No briefing provided."}</p>

              {a.tools.length > 0 && (
                <div className="agent-tools">
                  {a.tools.slice(0, 4).map((t) => (
                    <span className="agent-tool" key={t}>⚙ {t}</span>
                  ))}
                  {a.tools.length > 4 && (
                    <span className="agent-tool">+{a.tools.length - 4}</span>
                  )}
                </div>
              )}

              <span className="agent-cta">
                {a.locked
                  ? "SUBSCRIBE TO UNLOCK →"
                  : offline
                    ? "ENGINE OFFLINE"
                    : activeId === a.id
                      ? "READY — TRANSMIT BELOW"
                      : "DEPLOY →"}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
