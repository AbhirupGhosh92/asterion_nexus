import { useEffect, useState } from "react";
import { adminApi } from "../../models/api";
import type {
  AdminModel, AdminUser, EngineStatus, McpServer, QuotaConfig,
} from "../../models/types";

const TIERS = ["free", "pro", "admin"];
const PROVIDERS = ["vertexai", "vertexai_image", "ollama", "mock"];
const EMPTY_MODEL: AdminModel = {
  id: "", label: "", provider: "vertexai", model: "",
  min_tier: "free", enabled: true, extra: {},
};

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="engine-stat">
      <span className="engine-stat-value">{value}</span>
      <span className="quota-field-label">{label}</span>
    </div>
  );
}

export default function EngineTab({ onError }: { onError: (e: string | null) => void }) {
  const [st, setSt] = useState<EngineStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [output, setOutput] = useState<string>("");

  const refresh = () =>
    adminApi.engineStatus().then(setSt).catch((e) => onError(String(e)));

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function run(action: "start" | "stop" | "restart") {
    onError(null);
    setBusy(action);
    setOutput("");
    try {
      const r = await adminApi.engineControl(action);
      setOutput(r.output || (r.ok ? "done" : "failed"));
      if (!r.ok) onError(`Engine ${action} failed — see the log below.`);
      await refresh();
    } catch (e) {
      onError(String(e));
    } finally {
      setBusy(null);
    }
  }

  if (!st) return <div className="admin-scroll"><p className="cell-dim">loading…</p></div>;

  const MODE_LABEL: Record<string, string> = {
    docker: "local docker compose",
    vm: "compute engine vm",
    external: "external / hosted",
    none: "not configured",
  };

  return (
    <div className="admin-scroll">
      <div className="agent-form">
        <div className="engine-head">
          <span className={`pill ${st.reachable ? "pill-on" : "pill-off"}`}>
            {st.reachable ? "● ONLINE" : "● OFFLINE"}
          </span>
          <span className="cell-dim">{MODE_LABEL[st.mode] ?? st.mode}</span>
          {st.base_url && (
            <a
              className="engine-link"
              href={st.base_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              {st.base_url} ↗
            </a>
          )}
        </div>

        <div className="engine-stats">
          <Stat label="AGENTS" value={st.agents} />
          <Stat label="TOOLS" value={st.tools} />
          <Stat label="MCP LINKS" value={st.mcp_servers} />
          <Stat label="PLUGINS" value={st.plugins.length} />
          {st.containers && (
            <Stat
              label="CONTAINERS"
              value={`${st.containers.running}/${st.containers.total}`}
            />
          )}
          {st.vm && <Stat label="VM" value={st.vm.status} />}
        </div>

        {st.plugins.length > 0 && (
          <div className="tool-row">
            <span className="tool-row-label">PLUGINS:</span>
            {st.plugins.map((p) => (
              <span key={p} className="tool-chip">
                {p.split("/").pop()}
              </span>
            ))}
          </div>
        )}

        <div className="engine-actions">
          <button
            className={`admin-btn ${busy === "start" ? "thinking-indicator" : ""}`}
            disabled={!st.controllable || busy !== null}
            onClick={() => run("start")}
          >
            {busy === "start" ? "STARTING…" : "▶ START"}
          </button>
          <button
            className={`admin-btn ${busy === "restart" ? "thinking-indicator" : ""}`}
            disabled={!st.controllable || busy !== null}
            onClick={() => run("restart")}
          >
            {busy === "restart" ? "RESTARTING…" : "⟲ RESTART"}
          </button>
          <button
            className={`admin-btn admin-btn-danger ${busy === "stop" ? "thinking-indicator" : ""}`}
            disabled={!st.controllable || busy !== null}
            onClick={() => run("stop")}
          >
            {busy === "stop" ? "STOPPING…" : "■ STOP"}
          </button>
          <button className="admin-btn" onClick={refresh} disabled={busy !== null}>
            ⟳ REFRESH
          </button>
        </div>

        {!st.controllable && (
          <p className="cell-dim">
            Status only. Lifecycle control needs DIFY_COMPOSE_DIR (local docker) or
            DIFY_VM_NAME + DIFY_VM_ZONE (Compute Engine) in the backend env.
          </p>
        )}
        {!st.reachable && st.configured && (
          <p className="cell-dim">
            Agents are hidden from the model selector while the engine is offline.
          </p>
        )}
        {output && <pre className="engine-output">{output}</pre>}
      </div>
    </div>
  );
}
