import { useEffect, useState } from "react";
import { adminApi, type AdminModel, type AdminUser, type McpServer } from "./lib/apiClient";

const TIERS = ["free", "pro", "admin"];
const PROVIDERS = ["vertexai", "vertexai_image", "ollama", "mock"];

const EMPTY_MODEL: AdminModel = {
  id: "",
  label: "",
  provider: "vertexai",
  model: "",
  min_tier: "free",
  enabled: true,
  extra: {},
};

export default function AdminPanel({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<"users" | "models" | "agents" | "mcp">("users");
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="admin terminal-panel">
      <div className="admin-head">
        <div className="admin-tabs">
          <button
            className={`admin-tab ${tab === "users" ? "admin-tab-on" : ""}`}
            onClick={() => setTab("users")}
          >
            OPERATIVES
          </button>
          <button
            className={`admin-tab ${tab === "models" ? "admin-tab-on" : ""}`}
            onClick={() => setTab("models")}
          >
            MODEL GRID
          </button>
          <button
            className={`admin-tab ${tab === "agents" ? "admin-tab-on" : ""}`}
            onClick={() => setTab("agents")}
          >
            AGENT FORGE
          </button>
          <button
            className={`admin-tab ${tab === "mcp" ? "admin-tab-on" : ""}`}
            onClick={() => setTab("mcp")}
          >
            MCP LINKS
          </button>
        </div>
        <button className="hud-chip hud-signout" onClick={onClose}>
          ✕ CLOSE
        </button>
      </div>
      {error && <p className="gate-error">⚠ {error}</p>}
      {tab === "users" && <UsersTab onError={setError} />}
      {tab === "models" && <ModelsTab onError={setError} />}
      {tab === "agents" && <AgentsTab onError={setError} />}
      {tab === "mcp" && <McpTab onError={setError} />}
    </div>
  );
}

function McpTab({ onError }: { onError: (e: string | null) => void }) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ name: "", server_url: "" });

  const refresh = () => adminApi.listMcp().then(setServers).catch((e) => onError(String(e)));
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function link() {
    onError(null);
    if (!draft.name || !draft.server_url) {
      onError("name and server URL are required");
      return;
    }
    setBusy(true);
    try {
      const created = await adminApi.addMcp(draft);
      setDraft({ name: "", server_url: "" });
      refresh();
      if (created.tools.length === 0) {
        onError("Linked, but no tools discovered — check the server URL/transport.");
      }
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function unlink(id: string) {
    onError(null);
    try {
      await adminApi.deleteMcp(id);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  return (
    <div className="admin-scroll">
      <div className="agent-form">
        <div className="agent-form-row">
          <input
            className="admin-input"
            placeholder="name (e.g. deepwiki)"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
          <input
            className="admin-input"
            placeholder="server URL (streamable HTTP / SSE endpoint)"
            value={draft.server_url}
            onChange={(e) => setDraft({ ...draft, server_url: e.target.value })}
          />
        </div>
        <button
          className={`composer-send ${busy ? "thinking-indicator" : ""}`}
          onClick={link}
          disabled={busy}
        >
          {busy ? "LINKING…" : "🔌 LINK SERVER"}
        </button>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>SERVER</th>
            <th>TOOLS</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {servers.length === 0 && (
            <tr>
              <td colSpan={3} className="cell-dim">
                no MCP servers linked — linked tools join the AGENT FORGE arsenal automatically
              </td>
            </tr>
          )}
          {servers.map((s) => (
            <tr key={s.provider_id}>
              <td>
                <div className="cell-id">
                  <span>🔌 {s.name}</span>
                  <span className="cell-uid">{s.server_url}</span>
                </div>
              </td>
              <td className="cell-dim">{s.tools.join(", ") || "—"}</td>
              <td>
                <button className="admin-btn admin-btn-danger" onClick={() => unlink(s.provider_id)}>
                  UNLINK
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface ToolInfo {
  id: string;
  label: string;
  description: string;
}

function AgentsTab({ onError }: { onError: (e: string | null) => void }) {
  const [agents, setAgents] = useState<AdminModel[]>([]);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({
    id: "",
    name: "",
    instructions: "",
    model: "gemini-2.5-flash",
    min_tier: "free",
    tools: [] as string[],
  });

  const refresh = () => adminApi.listAgents().then(setAgents).catch((e) => onError(String(e)));
  useEffect(() => {
    refresh();
    adminApi.listTools().then(setTools).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      setDraft({
        id: "",
        name: "",
        instructions: "",
        model: "gemini-2.5-flash",
        min_tier: "free",
        tools: [],
      });
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
            <th>MODEL</th>
            <th>TOOLS</th>
            <th>MIN TIER</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {agents.length === 0 && (
            <tr>
              <td colSpan={5} className="cell-dim">
                no agents forged yet — they appear in every user's model selector once created
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

function UsersTab({ onError }: { onError: (e: string | null) => void }) {
  const [users, setUsers] = useState<AdminUser[]>([]);

  const refresh = () => adminApi.listUsers().then(setUsers).catch((e) => onError(String(e)));
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function changeTier(uid: string, tier: string) {
    onError(null);
    try {
      await adminApi.setTier(uid, tier);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  async function toggleDisabled(u: AdminUser) {
    onError(null);
    try {
      await adminApi.setDisabled(u.uid, !u.disabled);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  return (
    <div className="admin-scroll">
      <table className="admin-table">
        <thead>
          <tr>
            <th>IDENTITY</th>
            <th>TIER</th>
            <th>STATUS</th>
            <th>LAST SEEN</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.uid} className={u.disabled ? "row-disabled" : ""}>
              <td>
                <div className="cell-id">
                  <span>{u.email ?? u.display_name ?? "—"}</span>
                  <span className="cell-uid">{u.uid}</span>
                </div>
              </td>
              <td>
                <select
                  className="admin-select"
                  value={u.tier}
                  onChange={(e) => changeTier(u.uid, e.target.value)}
                >
                  {TIERS.map((t) => (
                    <option key={t} value={t}>
                      {t.toUpperCase()}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <span className={u.disabled ? "pill pill-off" : "pill pill-on"}>
                  {u.disabled ? "LOCKED" : "ACTIVE"}
                </span>
              </td>
              <td className="cell-dim">
                {u.last_sign_in ? new Date(u.last_sign_in).toLocaleDateString() : "never"}
              </td>
              <td>
                <button className="admin-btn" onClick={() => toggleDisabled(u)}>
                  {u.disabled ? "UNLOCK" : "LOCK"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ModelsTab({ onError }: { onError: (e: string | null) => void }) {
  const [models, setModels] = useState<AdminModel[]>([]);
  const [draft, setDraft] = useState<AdminModel>(EMPTY_MODEL);

  const refresh = () => adminApi.listModels().then(setModels).catch((e) => onError(String(e)));
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save() {
    onError(null);
    if (!draft.id || !draft.label || !draft.model) {
      onError("id, label, and model name are required");
      return;
    }
    try {
      await adminApi.upsertModel(draft);
      setDraft(EMPTY_MODEL);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  async function toggle(m: AdminModel) {
    onError(null);
    try {
      await adminApi.upsertModel({ ...m, enabled: !m.enabled });
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  async function remove(id: string) {
    onError(null);
    try {
      await adminApi.deleteModel(id);
      refresh();
    } catch (e) {
      onError(String(e));
    }
  }

  return (
    <div className="admin-scroll">
      <div className="model-form">
        <input
          className="admin-input"
          placeholder="id (e.g. gemini-pro)"
          value={draft.id}
          onChange={(e) => setDraft({ ...draft, id: e.target.value })}
        />
        <input
          className="admin-input"
          placeholder="label (e.g. Gemini 2.5 Pro)"
          value={draft.label}
          onChange={(e) => setDraft({ ...draft, label: e.target.value })}
        />
        <select
          className="admin-select"
          value={draft.provider}
          onChange={(e) => setDraft({ ...draft, provider: e.target.value })}
        >
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <input
          className="admin-input"
          placeholder="model name (e.g. gemini-2.5-pro)"
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
        <button className="composer-send" onClick={save}>
          + DEPLOY
        </button>
      </div>

      <table className="admin-table">
        <thead>
          <tr>
            <th>MODEL</th>
            <th>PROVIDER</th>
            <th>MIN TIER</th>
            <th>STATE</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id}>
              <td>
                <div className="cell-id">
                  <span>{m.label}</span>
                  <span className="cell-uid">
                    {m.id} · {m.model}
                  </span>
                </div>
              </td>
              <td className="cell-dim">{m.provider}</td>
              <td className="cell-dim">{m.min_tier.toUpperCase()}</td>
              <td>
                <button
                  className={m.enabled ? "pill pill-on pill-btn" : "pill pill-off pill-btn"}
                  onClick={() => toggle(m)}
                >
                  {m.enabled ? "ONLINE" : "OFFLINE"}
                </button>
              </td>
              <td>
                <button className="admin-btn admin-btn-danger" onClick={() => remove(m.id)}>
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
