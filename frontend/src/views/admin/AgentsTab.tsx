import { useEffect, useState } from "react";
import { adminApi } from "../../models/api";
import type {
  AdminModel, AdminUser, EngineStatus, McpServer, QuotaConfig,
} from "../../models/types";

// Specialist agents are a Pro capability — the backend floors any lower
// min_tier at "pro", so offering "free" here would be a lying control.
const TIERS = ["pro", "admin"];

// Two runtimes. LangGraph deep agents are the default: they run in-process,
// so they need no engine running and no external app to provision.
const ENGINES = [
  { id: "langgraph", label: "◈ DEEP AGENT (LangGraph)" },
  { id: "dify", label: "⚡ DIFY ENGINE" },
];
const PROVIDERS = ["vertexai", "vertexai_image", "ollama", "mock"];
const EMPTY_MODEL: AdminModel = {
  id: "", label: "", provider: "vertexai", model: "",
  min_tier: "free", enabled: true, extra: {},
};

interface ToolInfo {
  id: string;
  label: string;
  description: string;
}

export default function AgentsTab({ onError }: { onError: (e: string | null) => void }) {
  const [agents, setAgents] = useState<AdminModel[]>([]);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({
    id: "",
    name: "",
    instructions: "",
    model: "gemini-2.5-flash",
    min_tier: "pro",
    tools: [] as string[],
    engine: "langgraph",
  });

  const refresh = () => adminApi.listAgents().then(setAgents).catch((e) => onError(String(e)));
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Each engine has its own arsenal, and a tool selected for one is
  // meaningless to the other — so switching engines clears the loadout.
  useEffect(() => {
    adminApi.listTools(draft.engine).then(setTools).catch(() => setTools([]));
    setDraft((d) => ({ ...d, tools: [] }));
  }, [draft.engine]);

  function toggleTool(id: string) {
    setDraft((d) => ({
      ...d,
      tools: d.tools.includes(id) ? d.tools.filter((t) => t !== id) : [...d.tools, id],
    }));
  }

  async function forge() {
    onError(null);
    if (!draft.id || !draft.name || !draft.instructions) {
      onError("id, name, and instructions are required");
      return;
    }
    setBusy(true);
    try {
      await adminApi.createAgent(draft);
      setDraft((d) => ({
        id: "",
        name: "",
        instructions: "",
        model: "gemini-2.5-flash",
        min_tier: "pro",
        tools: [],
        engine: d.engine, // forging several agents on one engine is the norm
      }));
      refresh();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    onError(null);
    try {
      await adminApi.deleteAgent(id);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  return (
    <div className="admin-scroll">
      <div className="agent-form">
        <div className="agent-form-row">
          <select
            className="admin-select"
            value={draft.engine}
            onChange={(e) => setDraft({ ...draft, engine: e.target.value })}
            title="Which runtime executes this agent"
          >
            {ENGINES.map((e) => (
              <option key={e.id} value={e.id}>{e.label}</option>
            ))}
          </select>
          <input
            className="admin-input"
            placeholder="id (e.g. researcher)"
            value={draft.id}
            onChange={(e) => setDraft({ ...draft, id: e.target.value })}
          />
          <input
            className="admin-input"
            placeholder="name (e.g. Research Unit 7)"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
          <input
            className="admin-input"
            placeholder="model"
            value={draft.model}
            onChange={(e) => setDraft({ ...draft, model: e.target.value })}
          />
          <select
            className="admin-select"
            value={draft.min_tier}
            onChange={(e) => setDraft({ ...draft, min_tier: e.target.value })}
          >
            {TIERS.map((t) => (
              <option key={t} value={t}>
                min: {t}
              </option>
            ))}
          </select>
        </div>
        <textarea
          className="admin-input agent-instructions"
          placeholder="agent instructions / system prompt — what does this agent do?"
          rows={4}
          value={draft.instructions}
          onChange={(e) => setDraft({ ...draft, instructions: e.target.value })}
        />
        {tools.length > 0 && (
          <div className="tool-row">
            <span className="tool-row-label">ARSENAL:</span>
            {tools.map((t) => (
              <button
                key={t.id}
                className={`tool-chip ${draft.tools.includes(t.id) ? "tool-chip-on" : ""}`}
                title={t.description}
                onClick={() => toggleTool(t.id)}
              >
                {draft.tools.includes(t.id) ? "◉ " : "○ "}
                {t.label}
              </button>
            ))}
          </div>
        )}
        <button
          className={`composer-send ${busy ? "thinking-indicator" : ""}`}
          onClick={forge}
          disabled={busy}
        >
          {busy ? "FORGING…" : "⚡ FORGE AGENT"}
        </button>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>AGENT</th>
            <th>ENGINE</th>
            <th>MODEL</th>
            <th>TOOLS</th>
            <th>MIN TIER</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {agents.length === 0 && (
            <tr>
              <td colSpan={6} className="cell-dim">
                no agents forged yet — they appear on every Pro user's homepage once created
              </td>
            </tr>
          )}
          {agents.map((a) => (
            <tr key={a.id}>
              <td>
                <div className="cell-id">
                  <span>{a.label}</span>
                  <span className="cell-uid">{a.id}</span>
                </div>
              </td>
              <td className="cell-dim">
                {a.provider === "langgraph" ? "◈ DEEP" : "⚡ DIFY"}
              </td>
              <td className="cell-dim">{a.model}</td>
              <td className="cell-dim">{a.extra?.tools || "—"}</td>
              <td className="cell-dim">{a.min_tier.toUpperCase()}</td>
              <td>
                <button className="admin-btn admin-btn-danger" onClick={() => remove(a.id)}>
                  PURGE
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
