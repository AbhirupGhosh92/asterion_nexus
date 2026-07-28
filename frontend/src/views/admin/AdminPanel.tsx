import { useState } from "react";
import AgentsTab from "./AgentsTab";
import EngineTab from "./EngineTab";
import McpTab from "./McpTab";
import ModelsTab from "./ModelsTab";
import QuotasTab from "./QuotasTab";
import UsersTab from "./UsersTab";

type Tab = "users" | "quotas" | "models" | "agents" | "mcp" | "engine";

const TABS: { id: Tab; label: string }[] = [
  { id: "users", label: "OPERATIVES" },
  { id: "quotas", label: "QUOTAS" },
  { id: "models", label: "MODEL GRID" },
  { id: "agents", label: "AGENT FORGE" },
  { id: "mcp", label: "MCP LINKS" },
  { id: "engine", label: "ENGINE" },
];

/** Admin shell: tab chrome + shared error banner. Each tab is its own view. */
export default function AdminPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("users");
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="admin terminal-panel">
      <div className="admin-head">
        <div className="admin-tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`admin-tab ${tab === t.id ? "admin-tab-on" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <button className="hud-chip hud-signout" onClick={onClose}>
          ✕ CLOSE
        </button>
      </div>

      {error && <p className="gate-error">⚠ {error}</p>}

      {tab === "users" && <UsersTab onError={setError} />}
      {tab === "quotas" && <QuotasTab onError={setError} />}
      {tab === "models" && <ModelsTab onError={setError} />}
      {tab === "agents" && <AgentsTab onError={setError} />}
      {tab === "mcp" && <McpTab onError={setError} />}
      {tab === "engine" && <EngineTab onError={setError} />}
    </div>
  );
}
